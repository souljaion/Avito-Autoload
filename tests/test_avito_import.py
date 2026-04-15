"""Tests for avito_import: import items from Avito API, update existing, mark sold."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from app.services.avito_import import import_account_items


def _make_account(**kw):
    acc = MagicMock()
    acc.id = kw.get("id", 1)
    acc.name = kw.get("name", "TestAcc")
    acc.client_id = kw.get("client_id", "cid")
    acc.client_secret = kw.get("client_secret", "sec")
    acc.access_token = kw.get("access_token", "tok")
    acc.avito_user_id = kw.get("avito_user_id", 999)
    acc.token_expires_at = kw.get("token_expires_at", datetime.utcnow() + timedelta(hours=1))
    acc.autoload_enabled = kw.get("autoload_enabled", True)
    return acc


def _make_avito_item(avito_id, title="Item", price=5000, status="active"):
    return {
        "id": avito_id,
        "title": title,
        "price": price,
        "status": status,
        "category": {"id": 1, "name": "Одежда"},
        "description": "Описание товара",
        "url": f"https://avito.ru/items/{avito_id}",
    }


def _make_product(product_id, avito_id, status="active", removed_at=None, extra=None):
    p = MagicMock()
    p.id = product_id
    p.avito_id = avito_id
    p.status = status
    p.account_id = 1
    p.title = "Old Title"
    p.price = 1000
    p.description = "Old desc"
    p.category = "Одежда"
    p.removed_at = removed_at
    p.extra = extra or {}
    p.version = 1
    return p


def _mock_db_for_import(existing_products=None, all_avito_ids=None, stale_products=None):
    """Build a mock DB session that returns appropriate results for import_account_items.

    Query order:
      1. select(Product) WHERE avito_id IS NOT NULL AND account_id = X  → existing_products
      2. select(Product.avito_id) WHERE avito_id IS NOT NULL            → all_avito_ids
      3. select(Product) WHERE avito_id IS NULL AND sku IS NOT NULL      → unmatched (reconciliation)
      4. select(Product) WHERE account_id AND avito_id AND status IN... → stale_products
    """
    existing = existing_products or []
    all_ids = all_avito_ids if all_avito_ids is not None else [p.avito_id for p in existing]
    stale = stale_products if stale_products is not None else []

    # Result 1: existing products for this account
    existing_scalars = MagicMock()
    existing_scalars.all.return_value = existing
    existing_result = MagicMock()
    existing_result.scalars.return_value = existing_scalars

    # Result 2: all avito_ids across all accounts
    all_ids_result = MagicMock()
    all_ids_result.all.return_value = [(aid,) for aid in all_ids]

    # Result 3: unmatched products for reconciliation (empty by default)
    unmatched_scalars = MagicMock()
    unmatched_scalars.all.return_value = []
    unmatched_result = MagicMock()
    unmatched_result.scalars.return_value = unmatched_scalars

    # Result 4: stale products for sold marking
    stale_scalars = MagicMock()
    stale_scalars.all.return_value = stale
    stale_result = MagicMock()
    stale_result.scalars.return_value = stale_scalars

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=[existing_result, all_ids_result, unmatched_result, stale_result])
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()

    return mock_db


class TestAvitoImport:
    @pytest.mark.asyncio
    async def test_creates_new_product_for_unknown_item(self):
        """New avito item not in DB should create a Product + Listing."""
        account = _make_account()
        avito_items = [_make_avito_item(12345, "Nike Air", 5000)]

        mock_db = _mock_db_for_import(existing_products=[], all_avito_ids=[])

        with patch("app.services.avito_import.AvitoClient") as MockClient:
            instance = AsyncMock()
            instance.get_user_items = AsyncMock(return_value=avito_items)
            instance.close = AsyncMock()
            MockClient.return_value = instance

            result = await import_account_items(account, mock_db)

        assert result["imported"] == 1
        assert result["account"] == "TestAcc"
        # db.add should be called with Product and Listing
        assert mock_db.add.call_count >= 2
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_updates_existing_product(self):
        """Existing product should be updated with new title/price from Avito."""
        account = _make_account()
        existing = _make_product(1, avito_id=12345, status="active")
        avito_items = [_make_avito_item(12345, "Nike Air NEW", 6000)]

        mock_db = _mock_db_for_import(
            existing_products=[existing],
            all_avito_ids=[12345],
            stale_products=[],
        )

        with patch("app.services.avito_import.AvitoClient") as MockClient:
            instance = AsyncMock()
            instance.get_user_items = AsyncMock(return_value=avito_items)
            instance.close = AsyncMock()
            MockClient.return_value = instance

            result = await import_account_items(account, mock_db)

        assert result["updated"] == 1
        assert result["imported"] == 0
        assert existing.title == "Nike Air NEW"
        assert existing.price == 6000

    @pytest.mark.asyncio
    async def test_marks_missing_product_as_sold(self):
        """Product in DB but not in Avito API response should be marked as sold."""
        account = _make_account()
        stale = _make_product(1, avito_id=99999, status="active")
        avito_items = []  # nothing active on Avito

        mock_db = _mock_db_for_import(
            existing_products=[],
            all_avito_ids=[99999],
            stale_products=[stale],
        )

        with patch("app.services.avito_import.AvitoClient") as MockClient:
            instance = AsyncMock()
            instance.get_user_items = AsyncMock(return_value=avito_items)
            instance.close = AsyncMock()
            MockClient.return_value = instance

            result = await import_account_items(account, mock_db)

        assert result["marked_sold"] == 1
        assert stale.status == "sold"
        assert "sold_at" in stale.extra

    @pytest.mark.asyncio
    async def test_skips_restore_for_manually_removed(self):
        """Product removed manually (has removed_at) should NOT be restored."""
        account = _make_account()
        removed_product = _make_product(
            1, avito_id=55555, status="removed",
            removed_at=datetime.utcnow(),
        )
        avito_items = [_make_avito_item(55555, "Adidas", 3000)]

        mock_db = _mock_db_for_import(
            existing_products=[removed_product],
            all_avito_ids=[55555],
            stale_products=[],
        )

        with patch("app.services.avito_import.AvitoClient") as MockClient, \
             patch("app.services.avito_import.safe_update_status", new_callable=AsyncMock) as mock_safe:
            instance = AsyncMock()
            instance.get_user_items = AsyncMock(return_value=avito_items)
            instance.close = AsyncMock()
            MockClient.return_value = instance

            result = await import_account_items(account, mock_db)

        mock_safe.assert_not_called()
        assert result["updated"] == 1

    @pytest.mark.asyncio
    async def test_restores_sold_product_if_active_on_avito(self):
        """Sold product (no removed_at) reappearing on Avito should be restored."""
        account = _make_account()
        sold_product = _make_product(
            1, avito_id=77777, status="sold",
            removed_at=None,
        )
        avito_items = [_make_avito_item(77777, "Puma", 4000)]

        mock_db = _mock_db_for_import(
            existing_products=[sold_product],
            all_avito_ids=[77777],
            stale_products=[],
        )

        with patch("app.services.avito_import.AvitoClient") as MockClient, \
             patch("app.services.avito_import.safe_update_status", new_callable=AsyncMock, return_value=True) as mock_safe:
            instance = AsyncMock()
            instance.get_user_items = AsyncMock(return_value=avito_items)
            instance.close = AsyncMock()
            MockClient.return_value = instance

            result = await import_account_items(account, mock_db)

        mock_safe.assert_called_once()
        call_args = mock_safe.call_args
        assert call_args[0][2] == "imported"  # new_status

    @pytest.mark.asyncio
    async def test_rollback_on_exception(self):
        """DB error during import should trigger rollback, not commit."""
        account = _make_account()
        avito_items = [_make_avito_item(11111, "Error Item", 1000)]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=Exception("db error"))
        mock_db.commit = AsyncMock()
        mock_db.rollback = AsyncMock()

        with patch("app.services.avito_import.AvitoClient") as MockClient:
            instance = AsyncMock()
            instance.get_user_items = AsyncMock(return_value=avito_items)
            instance.close = AsyncMock()
            MockClient.return_value = instance

            result = await import_account_items(account, mock_db)

        assert "error" in result
        mock_db.rollback.assert_called_once()
        mock_db.commit.assert_not_called()
