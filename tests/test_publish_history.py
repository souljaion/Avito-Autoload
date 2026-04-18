"""Tests for product_publish_history recording during publish."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
import types

import pytest

from app.models.product_publish_history import ProductPublishHistory


class TestPublishHistoryModel:
    def test_model_fields(self):
        """Verify the model has all expected columns."""
        cols = ProductPublishHistory.__table__.columns.keys()
        assert "id" in cols
        assert "product_id" in cols
        assert "account_id" in cols
        assert "published_at" in cols
        assert "removed_at" in cols
        assert "was_uniquified" in cols

    def test_composite_index_exists(self):
        """Verify the composite index on (product_id, account_id)."""
        indexes = {idx.name for idx in ProductPublishHistory.__table__.indexes}
        assert "ix_product_publish_history_product_account" in indexes


class TestPublishScheduledRecordsHistory:
    """Verify that publish_scheduled_products records history on success."""

    @pytest.mark.asyncio
    async def test_history_recorded_on_publish(self):
        """When a listing is published, a ProductPublishHistory row should be added."""
        from app.services.publish_scheduled import publish_scheduled_products
        from app.models.listing import Listing
        from app.models.product import Product

        # Create mock product with images
        mock_img = MagicMock()
        mock_img.download_status = "ready"
        mock_img.was_uniquified = False

        mock_product = MagicMock(spec=Product)
        mock_product.id = 1
        mock_product.images = [mock_img]
        mock_product.status = "scheduled"
        mock_product.use_custom_description = False
        mock_product.description = "Test"
        mock_product.published_at = None
        mock_product.scheduled_at = None

        mock_listing = MagicMock(spec=Listing)
        mock_listing.id = 1
        mock_listing.account_id = 10
        mock_listing.product = mock_product
        mock_listing.status = "scheduled"
        mock_listing.images = []

        mock_account = MagicMock()
        mock_account.id = 10
        mock_account.name = "TestAccount"

        mock_tmpl = None

        # Mock DB
        db = AsyncMock()

        # execute returns: listings query, then template query
        scalars_listings = MagicMock()
        scalars_listings.all.return_value = [mock_listing]
        result_listings = MagicMock()
        result_listings.scalars.return_value = scalars_listings

        scalars_tmpl = MagicMock()
        scalars_tmpl.scalar_one_or_none = MagicMock(return_value=None)
        result_tmpl = MagicMock()
        result_tmpl.scalar_one_or_none = MagicMock(return_value=None)

        db.execute = AsyncMock(side_effect=[result_listings, result_tmpl])
        db.get = AsyncMock(return_value=mock_account)
        db.commit = AsyncMock()

        added_objects = []
        db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

        with patch("app.services.publish_scheduled.is_ready_for_feed", return_value=True):
            with patch("app.services.publish_scheduled.build_ad_element") as mock_build:
                from lxml import etree
                mock_build.return_value = etree.Element("Ad")
                with patch("app.services.publish_scheduled.AvitoClient") as MockClient:
                    client_instance = AsyncMock()
                    client_instance.upload_feed = AsyncMock(return_value={})
                    client_instance.close = AsyncMock()
                    MockClient.return_value = client_instance

                    result = await publish_scheduled_products(db)

        assert result["published"] == 1
        # Check that a ProductPublishHistory was added
        history_adds = [obj for obj in added_objects if isinstance(obj, ProductPublishHistory)]
        assert len(history_adds) == 1
        assert history_adds[0].product_id == 1
        assert history_adds[0].account_id == 10
        assert history_adds[0].was_uniquified is False


class TestPublishSkipsPendingPhotos:
    """Verify products with pending Yandex.Disk photos are skipped."""

    @pytest.mark.asyncio
    async def test_pending_photos_cause_skip(self):
        from app.services.publish_scheduled import publish_scheduled_products
        from app.models.listing import Listing

        mock_img_pending = MagicMock()
        mock_img_pending.download_status = "pending"

        mock_product = MagicMock()
        mock_product.id = 1
        mock_product.images = [mock_img_pending]
        mock_product.status = "scheduled"
        mock_product.use_custom_description = False
        mock_product.description = "Test"

        mock_listing = MagicMock(spec=Listing)
        mock_listing.id = 1
        mock_listing.account_id = 10
        mock_listing.product = mock_product
        mock_listing.status = "scheduled"
        mock_listing.images = []

        mock_account = MagicMock()
        mock_account.id = 10
        mock_account.name = "TestAccount"

        db = AsyncMock()
        scalars_listings = MagicMock()
        scalars_listings.all.return_value = [mock_listing]
        result_listings = MagicMock()
        result_listings.scalars.return_value = scalars_listings

        result_tmpl = MagicMock()
        result_tmpl.scalar_one_or_none = MagicMock(return_value=None)

        db.execute = AsyncMock(side_effect=[result_listings, result_tmpl])
        db.get = AsyncMock(return_value=mock_account)
        db.commit = AsyncMock()
        db.add = MagicMock()

        with patch("app.services.publish_scheduled.is_ready_for_feed", return_value=True):
            result = await publish_scheduled_products(db)

        # Product should be skipped, not published
        assert result["published"] == 0
        assert result["skipped"] == 1
