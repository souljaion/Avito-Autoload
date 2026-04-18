"""Tests for products API endpoints (ASGI transport, mock DB)."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from app.db import get_db
from app.routes.products import router


# ── Helpers ──


def _make_app(mock_db):
    app = FastAPI()
    app.include_router(router)

    async def override_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_db
    return app


def _make_product(pid=1, title="Test Product", price=1500, status="draft",
                  account_id=None, avito_id=None):
    p = MagicMock()
    p.id = pid
    p.title = title
    p.price = price
    p.status = status
    p.account_id = account_id
    p.avito_id = avito_id
    p.sku = None
    p.brand = None
    p.model = None
    p.category = None
    p.subcategory = None
    p.goods_type = None
    p.goods_subtype = None
    p.size = None
    p.color = None
    p.material = None
    p.condition = "Новое с биркой"
    p.description = "Test description"
    p.use_custom_description = False
    p.scheduled_at = None
    p.published_at = None
    p.removed_at = None
    p.scheduled_account_id = None
    p.image_url = None
    p.extra = {}
    p.version = 1
    p.variant_id = None
    p.model_id = None
    p.images = []
    p.account = None
    p.created_at = datetime(2026, 4, 18)
    p.updated_at = datetime(2026, 4, 18)
    return p


def _make_account(aid=1, name="TestAccount"):
    a = MagicMock()
    a.id = aid
    a.name = name
    a.client_id = "cid"
    a.description_template = None
    return a


# ── GET /products ──


class TestProductsList:
    @pytest.mark.asyncio
    async def test_products_list_returns_200(self):
        mock_result = MagicMock()
        mock_result.scalars.return_value.unique.return_value.all.return_value = []

        count_result = MagicMock()
        count_result.scalar.return_value = 0

        acct_result = MagicMock()
        acct_result.scalars.return_value.all.return_value = []

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=[acct_result, count_result, mock_result])

        app = _make_app(mock_db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/products")
        assert resp.status_code == 200


# ── POST /products/new ──


class TestCreateProduct:
    @pytest.mark.asyncio
    async def test_create_product_redirects(self):
        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        # After flush, the product gets an id assigned
        def fake_add(obj):
            obj.id = 42

        mock_db.add = MagicMock(side_effect=fake_add)

        app = _make_app(mock_db)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
            follow_redirects=False,
        ) as c:
            resp = await c.post(
                "/products/new",
                data={"title": "Test Product Pytest", "price": "1500", "status": "draft"},
            )
        assert resp.status_code == 303
        assert "/products/" in resp.headers.get("location", "")


# ── PATCH /products/{id} ──


class TestPatchProduct:
    @pytest.mark.asyncio
    async def test_patch_product_status(self):
        product = _make_product(pid=10, status="draft")
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=product)
        mock_db.commit = AsyncMock()

        app = _make_app(mock_db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.patch("/products/10", json={"status": "active"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["status"] == "active"

    @pytest.mark.asyncio
    async def test_patch_product_price(self):
        product = _make_product(pid=11, price=1000)
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=product)
        mock_db.commit = AsyncMock()

        app = _make_app(mock_db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.patch("/products/11", json={"price": 2500})
        assert resp.status_code == 200
        data = resp.json()
        assert data["price"] == 2500

    @pytest.mark.asyncio
    async def test_patch_nonexistent_product(self):
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)

        app = _make_app(mock_db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.patch("/products/999999", json={"status": "active"})
        assert resp.status_code == 404


# ── POST with account_id → auto-create listing ──


class TestProductWithListing:
    @pytest.mark.asyncio
    async def test_product_with_account_creates_listing(self):
        account = _make_account(aid=1)
        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()
        mock_db.get = AsyncMock(return_value=account)

        added_objects = []
        def fake_add(obj):
            if hasattr(obj, 'title'):
                obj.id = 55
            added_objects.append(obj)

        mock_db.add = MagicMock(side_effect=fake_add)

        app = _make_app(mock_db)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
            follow_redirects=False,
        ) as c:
            resp = await c.post(
                "/products/new",
                data={"title": "Auto Listing Test", "price": "3000",
                      "status": "draft", "account_id": "1"},
            )
        assert resp.status_code == 303

        # Verify a Listing object was added (product + listing = 2 adds)
        from app.models.listing import Listing
        listings = [o for o in added_objects if isinstance(o, Listing)]
        assert len(listings) == 1
        assert listings[0].account_id == 1


# ── Auth requirement ──


class TestAuthRequired:
    @pytest.mark.asyncio
    async def test_products_requires_auth(self):
        """Products page should require authentication (via middleware)."""
        from app.main import app as real_app
        async with AsyncClient(
            transport=ASGITransport(app=real_app), base_url="http://test",
        ) as c:
            resp = await c.get("/products")
        assert resp.status_code == 401
