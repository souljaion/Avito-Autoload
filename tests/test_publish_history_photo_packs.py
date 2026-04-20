"""Tests for PhotoPackPublishHistory recording in publish_scheduled."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.publish_scheduled import publish_scheduled_products
from app.models.photo_pack_publish_history import PhotoPackPublishHistory


def _make_account(acc_id=1, name="TestAcc"):
    return MagicMock(
        id=acc_id, name=name,
        client_id="cid", client_secret="sec",
        access_token="tok",
        token_expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1),
        phone="+79001234567", address="Москва",
    )


def _make_product(product_id=1, model_id=None):
    p = MagicMock()
    p.id = product_id
    p.status = "scheduled"
    p.model_id = model_id
    p.title = "Test"
    p.description = "Desc"
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
    img = MagicMock(url="/media/img.jpg", is_main=True, sort_order=0,
                    download_status="ready", was_uniquified=False)
    p.images = [img]
    p.scheduled_at = None
    p.published_at = None
    return p


def _make_listing(listing_id=1, account_id=1, product=None, account=None):
    ls = MagicMock()
    ls.id = listing_id
    ls.account_id = account_id
    ls.status = "scheduled"
    ls.scheduled_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=10)
    ls.published_at = None
    ls.product = product or _make_product()
    ls.account = account or _make_account(acc_id=account_id)
    ls.images = []
    return ls


def _mock_scalars(items):
    s = MagicMock()
    s.all.return_value = items
    r = MagicMock()
    r.scalars.return_value = s
    return r


class TestPublishHistoryPhotoPacks:
    @pytest.mark.asyncio
    async def test_no_model_id_no_pack_history(self):
        """Product without model_id → no PhotoPackPublishHistory, no crash."""
        product = _make_product(model_id=None)
        listing = _make_listing(product=product)

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=[
            _mock_scalars([listing]),  # listings
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),  # template
        ])
        mock_db.get = AsyncMock(return_value=_make_account())
        mock_db.commit = AsyncMock()
        added = []
        mock_db.add = MagicMock(side_effect=lambda obj: added.append(obj))

        with patch("app.services.publish_scheduled.is_ready_for_feed", return_value=True), \
             patch("app.services.publish_scheduled.build_ad_element") as mock_build, \
             patch("app.services.publish_scheduled.AvitoClient") as MockClient:
            from lxml import etree
            mock_build.return_value = etree.Element("Ad")
            c = AsyncMock()
            c.upload_feed = AsyncMock(return_value={})
            c.close = AsyncMock()
            MockClient.return_value = c

            result = await publish_scheduled_products(mock_db)

        assert result["published"] == 1
        pack_history = [o for o in added if isinstance(o, PhotoPackPublishHistory)]
        assert len(pack_history) == 0

    @pytest.mark.asyncio
    async def test_model_id_int_with_packs_records_history(self):
        """Product with int model_id + pack usage → PhotoPackPublishHistory inserted."""
        product = _make_product(model_id=5)
        listing = _make_listing(product=product)

        # Mock DB calls: listings, template, pack_usage, photo_packs
        # Note: publish_scheduled calls .all() directly on execute result (not .scalars().all())
        usage_result = MagicMock()
        usage_result.all.return_value = [(10,)]  # pack_id=10 used on account

        pack_result = MagicMock()
        pack_result.all.return_value = [(10,)]  # pack 10 belongs to model 5

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=[
            _mock_scalars([listing]),   # listings
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),  # template
            usage_result,               # pack_usage_history
            pack_result,                # photo_packs
        ])
        mock_db.get = AsyncMock(return_value=_make_account())
        mock_db.commit = AsyncMock()
        added = []
        mock_db.add = MagicMock(side_effect=lambda obj: added.append(obj))

        with patch("app.services.publish_scheduled.is_ready_for_feed", return_value=True), \
             patch("app.services.publish_scheduled.build_ad_element") as mock_build, \
             patch("app.services.publish_scheduled.AvitoClient") as MockClient:
            from lxml import etree
            mock_build.return_value = etree.Element("Ad")
            c = AsyncMock()
            c.upload_feed = AsyncMock(return_value={})
            c.close = AsyncMock()
            MockClient.return_value = c

            result = await publish_scheduled_products(mock_db)

        assert result["published"] == 1
        pack_history = [o for o in added if isinstance(o, PhotoPackPublishHistory)]
        assert len(pack_history) == 1
        assert pack_history[0].photo_pack_id == 10
        assert pack_history[0].account_id == 1

    @pytest.mark.asyncio
    async def test_pack_history_error_does_not_block_publish(self):
        """If pack history recording fails, publish itself still succeeds."""
        product = _make_product(model_id=99)
        listing = _make_listing(product=product)

        mock_db = AsyncMock()
        # Listings + template succeed, then pack queries raise
        mock_db.execute = AsyncMock(side_effect=[
            _mock_scalars([listing]),
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
            Exception("DB connection lost"),  # pack query fails
        ])
        mock_db.get = AsyncMock(return_value=_make_account())
        mock_db.commit = AsyncMock()
        mock_db.add = MagicMock()

        with patch("app.services.publish_scheduled.is_ready_for_feed", return_value=True), \
             patch("app.services.publish_scheduled.build_ad_element") as mock_build, \
             patch("app.services.publish_scheduled.AvitoClient") as MockClient:
            from lxml import etree
            mock_build.return_value = etree.Element("Ad")
            c = AsyncMock()
            c.upload_feed = AsyncMock(return_value={})
            c.close = AsyncMock()
            MockClient.return_value = c

            result = await publish_scheduled_products(mock_db)

        # Publish should still succeed despite pack history error
        assert result["published"] == 1
