"""Tests for categories routes: list, sync-tree, sync-fields."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from app.db import get_db
from app.routes.categories import router


def _make_app(mock_db):
    app = FastAPI()
    app.include_router(router)

    async def override_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_db
    return app


def _make_category(cid, name, slug=None, parent_id=None):
    c = MagicMock()
    c.id = cid
    c.name = name
    c.slug = slug or name.lower()
    c.parent_id = parent_id
    c.avito_id = cid * 10
    c.show_fields = False
    c.fields_data = None
    return c


def _make_account(aid=1, name="TestAcc"):
    a = MagicMock()
    a.id = aid
    a.name = name
    return a


class TestCategoryList:
    @pytest.mark.asyncio
    async def test_list_returns_html(self):
        """GET /categories should return HTML page."""
        # Query 1: count
        count_result = MagicMock()
        count_result.scalar.return_value = 5

        # Query 2: root categories
        roots_scalars = MagicMock()
        roots_scalars.all.return_value = []
        roots_result = MagicMock()
        roots_result.scalars.return_value = roots_scalars

        # Query 3: accounts
        accs_scalars = MagicMock()
        accs_scalars.all.return_value = []
        accs_result = MagicMock()
        accs_result.scalars.return_value = accs_scalars

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=[count_result, roots_result, accs_result])

        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/categories")

        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")


class TestSyncTree:
    @pytest.mark.asyncio
    async def test_sync_tree_account_not_found(self):
        """POST /categories/sync-tree with bad account_id should return 404."""
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/categories/sync-tree",
                data={"account_id": "999"},
                follow_redirects=False,
            )

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_sync_tree_success(self):
        """Successful sync should redirect with success message."""
        account = _make_account(aid=1)
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=account)
        app = _make_app(mock_db)

        with patch("app.routes.categories.AvitoClient") as MockClient, \
             patch("app.routes.categories.sync_tree", new_callable=AsyncMock, return_value=42):
            instance = AsyncMock()
            instance.close = AsyncMock()
            MockClient.return_value = instance

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/categories/sync-tree",
                    data={"account_id": "1"},
                    follow_redirects=False,
                )

        assert resp.status_code == 303
        assert "42" in resp.headers.get("location", "")

    @pytest.mark.asyncio
    async def test_sync_tree_error_redirects(self):
        """Exception during sync should redirect with error."""
        account = _make_account(aid=1)
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=account)
        mock_db.rollback = AsyncMock()
        app = _make_app(mock_db)

        with patch("app.routes.categories.AvitoClient") as MockClient, \
             patch("app.routes.categories.sync_tree", new_callable=AsyncMock, side_effect=RuntimeError("API fail")):
            instance = AsyncMock()
            instance.close = AsyncMock()
            MockClient.return_value = instance

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/categories/sync-tree",
                    data={"account_id": "1"},
                    follow_redirects=False,
                )

        assert resp.status_code == 303
        assert "error" in resp.headers.get("location", "").lower()


class TestSyncFields:
    @pytest.mark.asyncio
    async def test_sync_fields_account_not_found(self):
        """POST /categories/sync-fields with bad account_id should return 404."""
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/categories/sync-fields",
                data={"account_id": "999", "slug": "shoes"},
                follow_redirects=False,
            )

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_sync_fields_success(self):
        """Successful field sync should redirect with success."""
        account = _make_account(aid=1)
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=account)
        app = _make_app(mock_db)

        with patch("app.routes.categories.AvitoClient") as MockClient, \
             patch("app.routes.categories.sync_fields", new_callable=AsyncMock, return_value=True):
            instance = AsyncMock()
            instance.close = AsyncMock()
            MockClient.return_value = instance

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/categories/sync-fields",
                    data={"account_id": "1", "slug": "shoes"},
                    follow_redirects=False,
                )

        assert resp.status_code == 303
        assert "shoes" in resp.headers.get("location", "")

    @pytest.mark.asyncio
    async def test_sync_fields_not_found(self):
        """sync_fields returning False should redirect with error."""
        account = _make_account(aid=1)
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=account)
        app = _make_app(mock_db)

        with patch("app.routes.categories.AvitoClient") as MockClient, \
             patch("app.routes.categories.sync_fields", new_callable=AsyncMock, return_value=False):
            instance = AsyncMock()
            instance.close = AsyncMock()
            MockClient.return_value = instance

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/categories/sync-fields",
                    data={"account_id": "1", "slug": "nonexistent"},
                    follow_redirects=False,
                )

        assert resp.status_code == 303
        loc = resp.headers.get("location", "")
        assert "error" in loc.lower()

    @pytest.mark.asyncio
    async def test_sync_fields_unavailable(self):
        """FieldsUnavailable exception should redirect with error."""
        from app.services.category_sync import FieldsUnavailable

        account = _make_account(aid=1)
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=account)
        app = _make_app(mock_db)

        with patch("app.routes.categories.AvitoClient") as MockClient, \
             patch("app.routes.categories.sync_fields", new_callable=AsyncMock,
                   side_effect=FieldsUnavailable("Fields not available for this category")):
            instance = AsyncMock()
            instance.close = AsyncMock()
            MockClient.return_value = instance

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/categories/sync-fields",
                    data={"account_id": "1", "slug": "shoes"},
                    follow_redirects=False,
                )

        assert resp.status_code == 303
        assert "error" in resp.headers.get("location", "").lower()
