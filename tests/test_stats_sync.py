"""Tests for stats_sync: batch upsert of Avito item statistics."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.stats_sync import sync_stats_for_account, sync_all_stats


def _make_account(**kw):
    acc = MagicMock()
    acc.id = kw.get("id", 1)
    acc.name = kw.get("name", "TestAcc")
    acc.client_id = kw.get("client_id", "cid")
    acc.client_secret = kw.get("client_secret", "sec")
    acc.access_token = kw.get("access_token", "tok")
    acc.avito_user_id = kw.get("avito_user_id", 999)
    acc.token_expires_at = kw.get("token_expires_at", datetime.utcnow() + timedelta(hours=1))
    return acc


def _make_product(pid, avito_id, price=5000):
    p = MagicMock()
    p.id = pid
    p.avito_id = avito_id
    p.price = price
    p.account_id = 1
    return p


class TestStatsSync:
    @pytest.mark.asyncio
    async def test_no_products_returns_early(self):
        """Account with no products should return synced=0 without inserting."""
        account = _make_account()

        scalars = MagicMock()
        scalars.all.return_value = []
        result = MagicMock()
        result.scalars.return_value = scalars

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=result)
        mock_db.commit = AsyncMock()

        with patch("app.services.stats_sync.AvitoClient") as MockClient:
            client_inst = AsyncMock()
            client_inst.get_user_id = AsyncMock(return_value=999)
            client_inst.get_items_stats = AsyncMock(return_value={})
            client_inst.close = AsyncMock()
            MockClient.return_value = client_inst

            summary = await sync_stats_for_account(account, mock_db)

        assert summary["synced"] == 0
        assert summary["total"] == 0
        client_inst.get_items_stats.assert_not_called()

    @pytest.mark.asyncio
    async def test_batch_insert_called_once(self):
        """Stats for multiple products should be inserted in a single batch."""
        account = _make_account()
        products = [_make_product(1, 111), _make_product(2, 222), _make_product(3, 333)]

        scalars = MagicMock()
        scalars.all.return_value = products
        result = MagicMock()
        result.scalars.return_value = scalars

        mock_db = AsyncMock()
        # First execute = products query, second = batch insert
        mock_db.execute = AsyncMock(return_value=result)
        mock_db.commit = AsyncMock()

        stats_map = {
            111: {"views": 10, "contacts": 1, "favorites": 2},
            222: {"views": 20, "contacts": 3, "favorites": 4},
            333: {"views": 30, "contacts": 5, "favorites": 6},
        }

        with patch("app.services.stats_sync.AvitoClient") as MockClient:
            client_inst = AsyncMock()
            client_inst.get_items_stats = AsyncMock(return_value=stats_map)
            client_inst.close = AsyncMock()
            MockClient.return_value = client_inst

            summary = await sync_stats_for_account(account, mock_db)

        assert summary["synced"] == 3
        # execute called: 1 for products query + 1 for batch insert = 2
        assert mock_db.execute.call_count == 2
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_correct_values_in_batch(self):
        """Batch insert should contain correct views/contacts/favorites/price."""
        account = _make_account()
        product = _make_product(1, 111, price=5000)

        scalars = MagicMock()
        scalars.all.return_value = [product]
        result = MagicMock()
        result.scalars.return_value = scalars

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=result)
        mock_db.commit = AsyncMock()

        stats_map = {111: {"views": 50, "contacts": 3, "favorites": 7}}

        with patch("app.services.stats_sync.AvitoClient") as MockClient:
            client_inst = AsyncMock()
            client_inst.get_items_stats = AsyncMock(return_value=stats_map)
            client_inst.close = AsyncMock()
            MockClient.return_value = client_inst

            with patch("app.services.stats_sync.pg_insert") as mock_pg_insert:
                # Make pg_insert return a mock statement
                mock_stmt = MagicMock()
                mock_stmt.on_conflict_do_update.return_value = mock_stmt
                mock_pg_insert.return_value.values.return_value = mock_stmt

                summary = await sync_stats_for_account(account, mock_db)

        assert summary["synced"] == 1
        # Verify the values passed to pg_insert().values()
        values_call = mock_pg_insert.return_value.values.call_args[0][0]
        assert len(values_call) == 1
        row = values_call[0]
        assert row["product_id"] == 1
        assert row["avito_id"] == 111
        assert row["views"] == 50
        assert row["contacts"] == 3
        assert row["favorites"] == 7
        assert row["price"] == 5000

    @pytest.mark.asyncio
    async def test_empty_stats_still_commits(self):
        """When Avito returns empty stats, commit is called but no insert."""
        account = _make_account()
        products = [_make_product(1, 111)]

        scalars = MagicMock()
        scalars.all.return_value = products
        result = MagicMock()
        result.scalars.return_value = scalars

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=result)
        mock_db.commit = AsyncMock()

        with patch("app.services.stats_sync.AvitoClient") as MockClient:
            client_inst = AsyncMock()
            client_inst.get_items_stats = AsyncMock(return_value={})
            client_inst.close = AsyncMock()
            MockClient.return_value = client_inst

            summary = await sync_stats_for_account(account, mock_db)

        assert summary["synced"] == 0
        assert summary["total"] == 1
        # Only 1 execute (products query), no insert
        assert mock_db.execute.call_count == 1
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_api_error_propagates(self):
        """API error in get_items_stats should propagate (caught by sync_all_stats)."""
        account = _make_account()
        products = [_make_product(1, 111)]

        scalars = MagicMock()
        scalars.all.return_value = products
        result = MagicMock()
        result.scalars.return_value = scalars

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=result)
        mock_db.commit = AsyncMock()

        with patch("app.services.stats_sync.AvitoClient") as MockClient:
            client_inst = AsyncMock()
            client_inst.get_items_stats = AsyncMock(side_effect=Exception("API error"))
            client_inst.close = AsyncMock()
            MockClient.return_value = client_inst

            with pytest.raises(Exception, match="API error"):
                await sync_stats_for_account(account, mock_db)

        mock_db.commit.assert_not_called()
        client_inst.close.assert_called_once()  # cleanup in finally

    @pytest.mark.asyncio
    async def test_sync_all_catches_per_account_errors(self):
        """sync_all_stats should catch per-account errors and continue."""
        acc1 = _make_account(id=1, name="Good")
        acc2 = _make_account(id=2, name="Bad")

        accs_scalars = MagicMock()
        accs_scalars.all.return_value = [acc1, acc2]
        accs_result = MagicMock()
        accs_result.scalars.return_value = accs_scalars

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=accs_result)
        mock_db.commit = AsyncMock()

        with patch("app.services.stats_sync.sync_stats_for_account", new_callable=AsyncMock) as mock_sync:
            mock_sync.side_effect = [
                {"account": "Good", "synced": 5, "total": 5},
                Exception("API error for Bad"),
            ]
            results = await sync_all_stats(mock_db)

        assert len(results) == 2
        assert results[0]["synced"] == 5
        assert "error" in results[1]
