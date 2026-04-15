"""Tests for sold detection: items missing from Avito API get marked as sold."""

from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.sold_detection import check_and_mark_sold


def _make_account(**kw):
    defaults = {
        "id": 1,
        "name": "Test Account",
        "client_id": "test_id",
        "client_secret": "test_secret",
        "access_token": "token",
        "token_expires_at": datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1),
    }
    defaults.update(kw)
    return MagicMock(**defaults)


def _make_product(product_id, avito_id, status="active", extra=None):
    p = MagicMock()
    p.id = product_id
    p.avito_id = avito_id
    p.status = status
    p.account_id = 1
    p.extra = extra or {}
    p.version = 1
    return p


class TestCheckAndMarkSold:
    @pytest.mark.asyncio
    async def test_marks_missing_item_as_sold(self):
        """Product with avito_id not in API response should be marked as sold."""
        account = _make_account()

        # API returns 2 items (avito_id 100 and 200)
        avito_items = [{"id": 100}, {"id": 200}]

        # DB has 3 products (avito_id 100, 200, 300) — 300 is missing from API
        product_100 = _make_product(1, 100)
        product_200 = _make_product(2, 200)
        product_300 = _make_product(3, 300)

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [product_100, product_200, product_300]
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        with patch("app.services.sold_detection.AvitoClient") as MockClient, \
             patch("app.services.sold_detection.safe_update_status", new_callable=AsyncMock, return_value=True):
            instance = AsyncMock()
            instance.get_user_items = AsyncMock(return_value=avito_items)
            instance.close = AsyncMock()
            MockClient.return_value = instance

            result = await check_and_mark_sold(mock_db, account)

        assert result["checked"] == 3
        assert result["marked_sold"] == 1
        # Products 100 and 200 should stay active
        assert product_100.status == "active"
        assert product_200.status == "active"

    @pytest.mark.asyncio
    async def test_no_sold_when_all_present(self):
        """No products should be marked as sold when all are in the API response."""
        account = _make_account()

        avito_items = [{"id": 100}, {"id": 200}]
        product_100 = _make_product(1, 100)
        product_200 = _make_product(2, 200)

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [product_100, product_200]
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        with patch("app.services.sold_detection.AvitoClient") as MockClient:
            instance = AsyncMock()
            instance.get_user_items = AsyncMock(return_value=avito_items)
            instance.close = AsyncMock()
            MockClient.return_value = instance

            result = await check_and_mark_sold(mock_db, account)

        assert result["checked"] == 2
        assert result["marked_sold"] == 0
        # commit should not be called when nothing changed
        mock_db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_api_error_gracefully(self):
        """Should return error info when API call fails, not raise."""
        account = _make_account()
        mock_db = AsyncMock()

        with patch("app.services.sold_detection.AvitoClient") as MockClient:
            instance = AsyncMock()
            instance.get_user_items = AsyncMock(side_effect=Exception("API down"))
            instance.close = AsyncMock()
            MockClient.return_value = instance

            result = await check_and_mark_sold(mock_db, account)

        assert result["checked"] == 0
        assert result["marked_sold"] == 0
        assert "error" in result

    @pytest.mark.asyncio
    async def test_multiple_items_sold(self):
        """Multiple items missing from API should all be marked as sold."""
        account = _make_account()

        # API returns only item 100
        avito_items = [{"id": 100}]

        product_100 = _make_product(1, 100)
        product_200 = _make_product(2, 200)
        product_300 = _make_product(3, 300)

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [product_100, product_200, product_300]
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        with patch("app.services.sold_detection.AvitoClient") as MockClient, \
             patch("app.services.sold_detection.safe_update_status", new_callable=AsyncMock, return_value=True):
            instance = AsyncMock()
            instance.get_user_items = AsyncMock(return_value=avito_items)
            instance.close = AsyncMock()
            MockClient.return_value = instance

            result = await check_and_mark_sold(mock_db, account)

        assert result["marked_sold"] == 2
        mock_db.commit.assert_called_once()
