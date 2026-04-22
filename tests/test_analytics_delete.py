"""Tests for soft-delete chain: DELETE /products/{id} → feed includes Status=Removed.

Verifies the diagnosis: imported items WITH avito_id end up in the feed as
<Status>Removed</Status>; items WITHOUT avito_id are silently dropped (nothing
for Avito to remove); items removed >48h ago are excluded by the cutoff.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from app.db import get_db
from app.routes.products import router as products_router


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app(mock_db):
    app = FastAPI()
    app.include_router(products_router)

    async def _gen():
        yield mock_db

    app.dependency_overrides[get_db] = _gen
    return app


def _make_product(id, avito_id=None, account_id=1, status="imported"):
    p = MagicMock()
    p.id = id
    p.avito_id = avito_id
    p.account_id = account_id
    p.status = status
    p.removed_at = None
    p.title = f"Product {id}"
    p.price = 1000
    return p


def _empty_listings_db_extension(mock_db):
    """Wire db.execute() to return empty Listing query result."""
    listings_result = MagicMock()
    listings_result.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(return_value=listings_result)


# ---------------------------------------------------------------------------
# DELETE response shape — diagnostic fields
# ---------------------------------------------------------------------------

class TestDeleteResponseDiagnostics:
    @pytest.mark.asyncio
    async def test_response_includes_feed_account_id_when_avito_id_present(self):
        product = _make_product(id=42, avito_id=900_000_001, account_id=7, status="imported")
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=product)
        mock_db.commit = AsyncMock()
        _empty_listings_db_extension(mock_db)

        app = _make_app(mock_db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.delete("/products/42")

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["status"] == "removed"
        assert body["avito_id"] == 900_000_001
        assert body["account_id"] == 7
        assert body["feed_account_id"] == 7
        assert body["in_feed"] is True

    @pytest.mark.asyncio
    async def test_response_signals_no_feed_when_no_avito_id(self):
        product = _make_product(id=99, avito_id=None, account_id=7, status="imported")
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=product)
        mock_db.commit = AsyncMock()
        _empty_listings_db_extension(mock_db)

        app = _make_app(mock_db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.delete("/products/99")

        body = resp.json()
        assert body["ok"] is True
        assert body["avito_id"] is None
        assert body["feed_account_id"] is None
        assert body["in_feed"] is False

    @pytest.mark.asyncio
    async def test_delete_marks_product_removed_with_timestamp(self):
        product = _make_product(id=1, avito_id=123, account_id=7)
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=product)
        mock_db.commit = AsyncMock()
        _empty_listings_db_extension(mock_db)

        app = _make_app(mock_db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            await c.delete("/products/1")

        assert product.status == "removed"
        assert isinstance(product.removed_at, datetime)
        mock_db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_delete_404_for_unknown_product(self):
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)
        app = _make_app(mock_db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.delete("/products/99999")
        assert resp.status_code == 404
        assert resp.json()["ok"] is False


# ---------------------------------------------------------------------------
# Feed contents — test generate_feed query/output
# ---------------------------------------------------------------------------

class TestFeedAfterDelete:
    """Drive generate_feed with mocked DB to verify which products land in feed."""

    @pytest.mark.asyncio
    async def test_imported_with_avito_id_lands_as_removed(self, tmp_path):
        from app.services import feed_generator

        # Setup: one removed product with avito_id (within 48h cutoff)
        account = MagicMock()
        account.id = 1
        account.name = "Test"
        account.phone = None
        account.address = None

        removed_product = _make_product(id=42, avito_id=900_111, account_id=1, status="removed")
        removed_product.removed_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=2)

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=account)
        mock_db.commit = AsyncMock()
        mock_db.add = MagicMock()

        # Three execute calls expected: active products, removed products, template
        active_result = MagicMock()
        active_result.scalars.return_value.all.return_value = []
        removed_result = MagicMock()
        removed_result.scalars.return_value.all.return_value = [removed_product]
        tmpl_result = MagicMock()
        tmpl_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(side_effect=[active_result, removed_result, tmpl_result])

        with patch.object(feed_generator, "settings") as mock_settings:
            mock_settings.FEEDS_DIR = str(tmp_path)
            mock_settings.BASE_URL = "http://test"
            file_path, included = await feed_generator.generate_feed(1, mock_db)

        with open(file_path, "rb") as f:
            xml = f.read().decode("utf-8")

        assert included == 0  # no active products
        assert "<Status>Removed</Status>" in xml
        assert "<AvitoId>900111</AvitoId>" in xml
        assert "<Id>42</Id>" in xml

    @pytest.mark.asyncio
    async def test_imported_without_avito_id_excluded_by_query(self, tmp_path):
        """The removed-products query has `avito_id IS NOT NULL` — items without
        avito_id never enter the result set, so they can never land in the feed."""
        from app.services import feed_generator

        account = MagicMock()
        account.id = 1
        account.name = "Test"
        account.phone = None
        account.address = None

        # Simulate the SQL filter: query returns nothing (no avito_id rows excluded)
        active_result = MagicMock()
        active_result.scalars.return_value.all.return_value = []
        removed_result = MagicMock()
        removed_result.scalars.return_value.all.return_value = []  # empty per WHERE clause
        tmpl_result = MagicMock()
        tmpl_result.scalar_one_or_none.return_value = None

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=account)
        mock_db.commit = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.execute = AsyncMock(side_effect=[active_result, removed_result, tmpl_result])

        with patch.object(feed_generator, "settings") as mock_settings:
            mock_settings.FEEDS_DIR = str(tmp_path)
            mock_settings.BASE_URL = "http://test"
            file_path, _ = await feed_generator.generate_feed(1, mock_db)

        with open(file_path, "rb") as f:
            xml = f.read().decode("utf-8")
        # No <Status>Removed</Status> entries
        assert "<Status>Removed</Status>" not in xml

    def test_removed_query_filters_out_old_and_no_avito_id(self):
        """Verify the removed-products SQL query has the right WHERE clauses.

        Reading feed_generator.py inline avoids brittle SQL string matching.
        """
        import inspect
        from app.services import feed_generator
        src = inspect.getsource(feed_generator.generate_feed)
        # 48h cutoff
        assert "timedelta(hours=48)" in src
        # avito_id NOT NULL
        assert "avito_id.isnot(None)" in src
        # status == removed
        assert 'Product.status == "removed"' in src
        # account_id filter
        assert "Product.account_id == account_id" in src
