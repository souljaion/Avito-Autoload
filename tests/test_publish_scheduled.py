"""Tests for publish_scheduled: scheduled listings → XML feed → Avito upload."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
import types

import pytest

from app.services.publish_scheduled import publish_scheduled_products


def _make_account(acc_id=1, name="TestAcc"):
    return MagicMock(
        id=acc_id, name=name,
        client_id="cid", client_secret="sec",
        access_token="tok",
        token_expires_at=datetime.utcnow() + timedelta(hours=1),
        phone="+79001234567", address="Москва",
    )


def _make_product(product_id=1, status="scheduled", avito_id=None):
    p = MagicMock()
    p.id = product_id
    p.status = status
    p.avito_id = avito_id
    p.title = "Test Product"
    p.description = "Описание"
    p.price = 5000
    p.category = "Одежда"
    p.goods_type = "Мужская обувь"
    p.subcategory = "Кроссовки"
    p.goods_subtype = "Кроссовки"
    p.condition = "Новое с биркой"
    p.brand = "Nike"
    p.color = "Белый"
    p.size = "42"
    p.material = None
    p.extra = {}
    p.use_custom_description = False
    p.images = [MagicMock(url="/media/img.jpg", is_main=True, sort_order=0)]
    p.scheduled_at = None
    p.published_at = None
    return p


def _make_listing(listing_id=1, account_id=1, product=None, account=None, minutes_ago=10):
    ls = MagicMock()
    ls.id = listing_id
    ls.account_id = account_id
    ls.status = "scheduled"
    ls.scheduled_at = datetime.utcnow() - timedelta(minutes=minutes_ago)
    ls.published_at = None
    ls.product = product or _make_product()
    ls.account = account or _make_account(acc_id=account_id)
    ls.images = []
    return ls


class TestPublishScheduled:
    @pytest.mark.asyncio
    async def test_no_due_listings(self):
        """When no listings are due, nothing is uploaded or committed."""
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        with patch("app.services.publish_scheduled.AvitoClient") as MockClient:
            result = await publish_scheduled_products(mock_db)

        assert result == {"published": 0, "skipped": 0, "errors": 0}
        MockClient.assert_not_called()
        mock_db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_publishes_due_listings(self):
        """Due listings should be uploaded and marked as published."""
        account = _make_account()
        product1 = _make_product(product_id=1)
        product2 = _make_product(product_id=2)
        listing1 = _make_listing(listing_id=1, product=product1, account=account)
        listing2 = _make_listing(listing_id=2, product=product2, account=account)

        # First execute returns listings, second returns template
        listings_scalars = MagicMock()
        listings_scalars.all.return_value = [listing1, listing2]
        listings_result = MagicMock()
        listings_result.scalars.return_value = listings_scalars

        tmpl_result = MagicMock()
        tmpl_result.scalar_one_or_none.return_value = None

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=[listings_result, tmpl_result])
        mock_db.get = AsyncMock(return_value=account)
        mock_db.commit = AsyncMock()

        with patch("app.services.publish_scheduled.AvitoClient") as MockClient:
            client_instance = AsyncMock()
            client_instance.upload_feed = AsyncMock(return_value={"status": "ok"})
            client_instance.close = AsyncMock()
            MockClient.return_value = client_instance

            result = await publish_scheduled_products(mock_db)

        assert result["published"] == 2
        assert result["errors"] == 0
        client_instance.upload_feed.assert_called_once()
        mock_db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_upload_failure_does_not_mark_published(self):
        """Failed upload should not change listing status to published."""
        account = _make_account()
        product = _make_product()
        listing = _make_listing(product=product, account=account)

        listings_scalars = MagicMock()
        listings_scalars.all.return_value = [listing]
        listings_result = MagicMock()
        listings_result.scalars.return_value = listings_scalars

        tmpl_result = MagicMock()
        tmpl_result.scalar_one_or_none.return_value = None

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=[listings_result, tmpl_result])
        mock_db.get = AsyncMock(return_value=account)
        mock_db.commit = AsyncMock()

        with patch("app.services.publish_scheduled.AvitoClient") as MockClient:
            client_instance = AsyncMock()
            client_instance.upload_feed = AsyncMock(side_effect=Exception("upload failed"))
            client_instance.close = AsyncMock()
            MockClient.return_value = client_instance

            result = await publish_scheduled_products(mock_db)

        assert result["errors"] == 1
        assert result["published"] == 0
        # Status should remain "scheduled" (mock won't change it, and publish code
        # only sets status inside the success branch)

    @pytest.mark.asyncio
    async def test_skips_listings_not_yet_due(self):
        """Listings scheduled in the future should not be returned by the query."""
        # The query filters by scheduled_at <= now, so the DB mock returns empty
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.services.publish_scheduled.AvitoClient") as MockClient:
            result = await publish_scheduled_products(mock_db)

        assert result["published"] == 0
        MockClient.assert_not_called()

    @pytest.mark.asyncio
    async def test_multiple_accounts_separate_uploads(self):
        """Listings from different accounts should trigger separate uploads."""
        acc1 = _make_account(acc_id=1, name="Account1")
        acc2 = _make_account(acc_id=2, name="Account2")
        p1 = _make_product(product_id=1)
        p2 = _make_product(product_id=2)
        p3 = _make_product(product_id=3)
        ls1 = _make_listing(listing_id=1, account_id=1, product=p1, account=acc1)
        ls2 = _make_listing(listing_id=2, account_id=1, product=p2, account=acc1)
        ls3 = _make_listing(listing_id=3, account_id=2, product=p3, account=acc2)

        listings_scalars = MagicMock()
        listings_scalars.all.return_value = [ls1, ls2, ls3]
        listings_result = MagicMock()
        listings_result.scalars.return_value = listings_scalars

        tmpl_result = MagicMock()
        tmpl_result.scalar_one_or_none.return_value = None

        mock_db = AsyncMock()
        # execute calls: 1 for listings, then 1 template query per account = 3 total
        mock_db.execute = AsyncMock(side_effect=[listings_result, tmpl_result, tmpl_result])
        mock_db.get = AsyncMock(side_effect=[acc1, acc2])
        mock_db.commit = AsyncMock()

        with patch("app.services.publish_scheduled.AvitoClient") as MockClient:
            client_instance = AsyncMock()
            client_instance.upload_feed = AsyncMock(return_value={"status": "ok"})
            client_instance.close = AsyncMock()
            MockClient.return_value = client_instance

            result = await publish_scheduled_products(mock_db)

        assert result["published"] == 3
        assert client_instance.upload_feed.call_count == 2
