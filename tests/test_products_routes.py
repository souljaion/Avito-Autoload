"""Unit tests for app/routes/products.py using mock DB."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from app.db import get_db
from app.routes.products import router


# ── Helpers ─────────────────────────────────────────────────────────


def _make_app(mock_db):
    app = FastAPI()
    app.include_router(router)

    async def override_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_db
    return app


def _empty_db():
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_result.scalars.return_value.unique.return_value.all.return_value = []
    mock_result.scalar.return_value = None
    mock_result.scalar_one_or_none.return_value = None
    mock_result.all.return_value = []

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.get = AsyncMock(return_value=None)
    mock_db.commit = AsyncMock()
    mock_db.flush = AsyncMock()
    return mock_db


def _make_account(id=1, name="TestAccount", client_id="cid", avito_sync_minute=None):
    acc = MagicMock()
    acc.id = id
    acc.name = name
    acc.client_id = client_id
    acc.avito_sync_minute = avito_sync_minute
    acc.description_template = None
    return acc


def _make_image(url="/media/products/1/img.jpg", is_main=True, sort_order=0):
    img = MagicMock()
    img.url = url
    img.is_main = is_main
    img.sort_order = sort_order
    return img


def _make_product(
    id=1, avito_id=None, title="Nike Air Max", price=5000, status="draft",
    account_id=1, account=None, images=None, model_id=None,
    sku="SKU-001", brand="Nike", model="Air Max",
    category="Одежда, обувь, аксессуары", goods_type="Мужская обувь",
    subcategory="Кроссовки и кеды", goods_subtype="Кроссовки",
    size="42", color="Black", material="Leather", condition="Новое с биркой",
    description="Test description", scheduled_at=None, removed_at=None,
    extra=None, use_custom_description=False, image_url=None, version=1,
    published_at=None,
):
    p = MagicMock()
    p.id = id
    p.avito_id = avito_id
    p.title = title
    p.price = price
    p.status = status
    p.account_id = account_id
    p.account = account or _make_account(id=account_id)
    p.images = images if images is not None else [_make_image()]
    p.model_id = model_id
    p.sku = sku
    p.brand = brand
    p.model = model
    p.category = category
    p.goods_type = goods_type
    p.subcategory = subcategory
    p.goods_subtype = goods_subtype
    p.size = size
    p.color = color
    p.material = material
    p.condition = condition
    p.description = description
    p.scheduled_at = scheduled_at
    p.removed_at = removed_at
    p.extra = extra or {}
    p.use_custom_description = use_custom_description
    p.image_url = image_url
    p.version = version
    p.published_at = published_at
    return p


# ── GET /products/search ────────────────────────────────────────────


class TestSearchProducts:
    @pytest.mark.asyncio
    async def test_search_too_short_query(self):
        """Query shorter than 2 chars returns empty list."""
        mock_db = _empty_db()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/products/search?q=a")

        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_search_empty_query(self):
        """Empty query returns empty list."""
        mock_db = _empty_db()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/products/search?q=")

        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_search_returns_products(self):
        """Valid query returns matching products."""
        product = _make_product(id=10, title="Nike Air Max 90", price=7000)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [product]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/products/search?q=Nike Air")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == 10
        assert data[0]["title"] == "Nike Air Max 90"
        assert data[0]["price"] == 7000

    @pytest.mark.asyncio
    async def test_search_with_account_filter(self):
        """Search with account_id filter."""
        product = _make_product(id=5, title="Adidas Superstar", account_id=2)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [product]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/products/search?q=Adidas&account_id=2")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == 5

    @pytest.mark.asyncio
    async def test_search_product_no_images_uses_image_url(self):
        """Product without images uses image_url fallback."""
        product = _make_product(id=3, images=[], image_url="/fallback.jpg")
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [product]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/products/search?q=Nike Air")

        assert resp.status_code == 200
        data = resp.json()
        assert data[0]["image_url"] == "/fallback.jpg"

    @pytest.mark.asyncio
    async def test_search_product_no_account(self):
        """Product without account returns null account_name."""
        product = _make_product(id=4, account_id=None)
        product.account = None
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [product]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/products/search?q=Nike Air")

        assert resp.status_code == 200
        assert resp.json()[0]["account_name"] is None


# ── PATCH /products/{id} ────────────────────────────────────────────


class TestPatchProduct:
    @pytest.mark.asyncio
    async def test_patch_not_found(self):
        """PATCH on non-existent product returns 404."""
        mock_db = _empty_db()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch("/products/999", json={"status": "active"})

        assert resp.status_code == 404
        assert resp.json()["ok"] is False

    @pytest.mark.asyncio
    async def test_patch_invalid_status(self):
        """PATCH with invalid status returns 400."""
        product = _make_product(id=1)
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=product)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch("/products/1", json={"status": "nonexistent"})

        assert resp.status_code == 400
        assert "Недопустимый статус" in resp.json()["error"]

    @pytest.mark.asyncio
    async def test_patch_invalid_price(self):
        """PATCH with non-numeric price returns 400."""
        product = _make_product(id=1)
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=product)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch("/products/1", json={"price": "abc"})

        assert resp.status_code == 400
        assert "Некорректная цена" in resp.json()["error"]

    @pytest.mark.asyncio
    async def test_patch_cancel_scheduled(self):
        """PATCH scheduled->draft clears scheduled_at and updates listings."""
        product = _make_product(id=1, status="scheduled", scheduled_at=datetime.utcnow())

        listing = MagicMock()
        listing.status = "scheduled"
        listing.scheduled_at = datetime.utcnow()

        listing_result = MagicMock()
        listing_result.scalars.return_value.all.return_value = [listing]

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=product)
        mock_db.execute = AsyncMock(return_value=listing_result)
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch("/products/1", json={"status": "draft"})

        assert resp.status_code == 200
        assert resp.json()["status"] == "draft"
        assert product.scheduled_at is None
        assert listing.status == "draft"
        assert listing.scheduled_at is None

    @pytest.mark.asyncio
    async def test_patch_description(self):
        """PATCH description updates the product."""
        product = _make_product(id=1)
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=product)
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch("/products/1", json={"description": "New desc"})

        assert resp.status_code == 200
        assert product.description == "New desc"

    @pytest.mark.asyncio
    async def test_patch_use_custom_description(self):
        """PATCH use_custom_description flag."""
        product = _make_product(id=1, use_custom_description=False)
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=product)
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch("/products/1", json={"use_custom_description": True})

        assert resp.status_code == 200
        assert product.use_custom_description is True

    @pytest.mark.asyncio
    async def test_patch_model_id(self):
        """PATCH model_id."""
        product = _make_product(id=1, model_id=None)
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=product)
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch("/products/1", json={"model_id": 42})

        assert resp.status_code == 200
        assert product.model_id == 42

    @pytest.mark.asyncio
    async def test_patch_null_price(self):
        """PATCH price to None clears the price."""
        product = _make_product(id=1, price=5000)
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=product)
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch("/products/1", json={"price": None})

        assert resp.status_code == 200
        assert product.price is None

    @pytest.mark.asyncio
    async def test_patch_description_template_id_valid(self):
        """PATCH with valid description_template_id saves FK."""
        product = _make_product(id=1)
        product.description_template_id = None
        tpl = MagicMock()
        tpl.id = 10

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(side_effect=lambda model, pk: product if model.__name__ == "Product" else tpl)
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch("/products/1", json={"description_template_id": 10})

        assert resp.status_code == 200
        assert product.description_template_id == 10

    @pytest.mark.asyncio
    async def test_patch_description_template_id_not_found(self):
        """PATCH with nonexistent template_id returns 404."""
        product = _make_product(id=1)
        product.description_template_id = None

        mock_db = AsyncMock()

        async def mock_get(model, pk):
            if hasattr(model, "__tablename__") and model.__tablename__ == "products":
                return product
            return None

        mock_db.get = AsyncMock(side_effect=mock_get)
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch("/products/1", json={"description_template_id": 999})

        assert resp.status_code == 404
        assert "Шаблон с id=999 не найден" in resp.json()["error"]

    @pytest.mark.asyncio
    async def test_patch_description_template_id_null_clears(self):
        """PATCH with description_template_id=null clears the FK."""
        product = _make_product(id=1)
        product.description_template_id = 10

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=product)
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch("/products/1", json={"description_template_id": None})

        assert resp.status_code == 200
        assert product.description_template_id is None


# ── DELETE /products/{id} ───────────────────────────────────────────


class TestDeleteProduct:
    @pytest.mark.asyncio
    async def test_delete_not_found(self):
        """DELETE on non-existent product returns 404."""
        mock_db = _empty_db()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.delete("/products/999")

        assert resp.status_code == 404
        assert resp.json()["ok"] is False

    @pytest.mark.asyncio
    async def test_delete_sets_removed(self):
        """DELETE sets status=removed and removed_at, updates listings."""
        product = _make_product(id=1, status="active")

        listing = MagicMock()
        listing.status = "active"
        listing_result = MagicMock()
        listing_result.scalars.return_value.all.return_value = [listing]

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=product)
        mock_db.execute = AsyncMock(return_value=listing_result)
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.delete("/products/1")

        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert product.status == "removed"
        assert product.removed_at is not None
        assert listing.status == "draft"

    @pytest.mark.asyncio
    async def test_delete_with_avito_id(self):
        """DELETE product with avito_id returns avito_id in response."""
        product = _make_product(id=10, status="active", avito_id=12345, account_id=1)

        listing_result = MagicMock()
        listing_result.scalars.return_value.all.return_value = []

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=product)
        mock_db.execute = AsyncMock(return_value=listing_result)
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.delete("/products/10")

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["avito_id"] == 12345
        assert data["status"] == "removed"
        assert product.status == "removed"

    @pytest.mark.asyncio
    async def test_delete_without_avito_id(self):
        """DELETE product without avito_id — simple local removal."""
        product = _make_product(id=12, status="draft", avito_id=None, account_id=1)

        listing_result = MagicMock()
        listing_result.scalars.return_value.all.return_value = []

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=product)
        mock_db.execute = AsyncMock(return_value=listing_result)
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.delete("/products/12")

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["avito_id"] is None
        assert product.status == "removed"


# ── POST /products/{id}/duplicate ───────────────────────────────────


class TestDuplicateProduct:
    @pytest.mark.asyncio
    async def test_duplicate_not_found(self):
        """Duplicate of non-existent product returns 404."""
        mock_db = _empty_db()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/products/999/duplicate", follow_redirects=False)

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_duplicate_creates_copy(self):
        """Duplicate creates a copy and redirects."""
        product = _make_product(id=1, title="Original", price=3000, extra={"ad_type": "test"})

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=product)
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/products/1/duplicate", follow_redirects=False)

        assert resp.status_code == 303
        assert "/edit" in resp.headers["location"]
        # Verify db.add was called (once for product copy, once for listing)
        assert mock_db.add.call_count >= 1


# ── POST /products/{id}/schedule ────────────────────────────────────


class TestScheduleProduct:
    @pytest.mark.asyncio
    async def test_schedule_missing_fields(self):
        """Schedule without required fields returns 400."""
        mock_db = _empty_db()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/products/1/schedule", json={})

        assert resp.status_code == 400
        assert resp.json()["ok"] is False

    @pytest.mark.asyncio
    async def test_schedule_product_not_found(self):
        """Schedule non-existent product returns 404."""
        mock_db = _empty_db()
        # First execute returns no product
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/products/999/schedule",
                json={"account_id": 1, "scheduled_at": "2026-05-01T10:00"},
            )

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_schedule_not_ready(self):
        """Schedule product missing required fields returns 400 with problems."""
        product = _make_product(
            id=1, title="Incomplete", description=None, price=None,
            category=None, goods_type=None, subcategory=None,
            goods_subtype=None, images=[],
        )

        call_count = [0]

        def make_result(*args, **kwargs):
            call_count[0] += 1
            r = MagicMock()
            if call_count[0] == 1:  # product query
                r.scalar_one_or_none.return_value = product
            elif call_count[0] == 2:  # template query
                r.scalar_one_or_none.return_value = None
            return r

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=make_result)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/products/1/schedule",
                json={"account_id": 1, "scheduled_at": "2026-05-01T10:00"},
            )

        assert resp.status_code == 400
        data = resp.json()
        assert data["ok"] is False
        assert "problems" in data
        assert len(data["problems"]) > 0

    @pytest.mark.asyncio
    async def test_schedule_success(self):
        """Successful scheduling sets status and returns display time."""
        product = _make_product(id=1)
        account = _make_account(id=1, avito_sync_minute=30)

        call_count = [0]

        def make_result(*args, **kwargs):
            call_count[0] += 1
            r = MagicMock()
            if call_count[0] == 1:  # product query
                r.scalar_one_or_none.return_value = product
            elif call_count[0] == 2:  # template check
                r.scalar_one_or_none.return_value = None
            elif call_count[0] == 3:  # listing query
                r.scalar_one_or_none.return_value = None
            return r

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=make_result)
        mock_db.get = AsyncMock(return_value=account)
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/products/1/schedule",
                json={"account_id": 1, "scheduled_at": "2026-05-01T10:00"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "scheduled_at" in data
        assert data["sync_hint"] is not None
        assert product.status == "scheduled"

    @pytest.mark.asyncio
    async def test_schedule_invalid_datetime(self):
        """Schedule with bad datetime returns 400."""
        product = _make_product(id=1)

        call_count = [0]

        def make_result(*args, **kwargs):
            call_count[0] += 1
            r = MagicMock()
            if call_count[0] == 1:  # product query
                r.scalar_one_or_none.return_value = product
            elif call_count[0] == 2:  # template check
                r.scalar_one_or_none.return_value = None
            return r

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=make_result)
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/products/1/schedule",
                json={"account_id": 1, "scheduled_at": "not-a-date"},
            )

        assert resp.status_code == 400


# ── DELETE /products/{id}/schedule ──────────────────────────────────


class TestCancelSchedule:
    @pytest.mark.asyncio
    async def test_cancel_schedule_no_listings(self):
        """Cancel schedule with no scheduled listings still returns ok."""
        mock_db = _empty_db()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.delete("/products/1/schedule")

        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    @pytest.mark.asyncio
    async def test_cancel_schedule_updates_listings(self):
        """Cancel schedule sets listings to draft."""
        listing = MagicMock()
        listing.status = "scheduled"
        listing.scheduled_at = datetime.utcnow()

        listing_result = MagicMock()
        listing_result.scalars.return_value.all.return_value = [listing]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=listing_result)
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.delete("/products/1/schedule")

        assert resp.status_code == 200
        assert listing.status == "draft"
        assert listing.scheduled_at is None


# ── GET /products/{id}/avito-status ─────────────────────────────────


class TestAvitoStatus:
    @pytest.mark.asyncio
    async def test_avito_status_not_found(self):
        """Avito status for non-existent product returns 404."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/products/999/avito-status")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_avito_status_no_account(self):
        """Avito status with no account returns 400."""
        product = _make_product(id=1)
        product.account = None
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = product

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/products/1/avito-status")

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_avito_status_success(self):
        """Avito status returns item info from AvitoClient."""
        product = _make_product(id=1, account=_make_account())
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = product

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        app = _make_app(mock_db)

        with patch("app.routes.products.AvitoClient") as MockClient:
            instance = AsyncMock()
            instance.get_items_info = AsyncMock(return_value=[{
                "avito_status": "active",
                "url": "https://avito.ru/item/123",
                "messages": [],
                "processing_time": None,
                "avito_date_end": None,
            }])
            instance.close = AsyncMock()
            MockClient.return_value = instance

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get("/products/1/avito-status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["avito_status"] == "active"
        assert data["url"] == "https://avito.ru/item/123"

    @pytest.mark.asyncio
    async def test_avito_status_api_error(self):
        """Avito API error returns 502."""
        product = _make_product(id=1, account=_make_account())
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = product

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        app = _make_app(mock_db)

        with patch("app.routes.products.AvitoClient") as MockClient:
            instance = AsyncMock()
            instance.get_items_info = AsyncMock(side_effect=Exception("API down"))
            instance.close = AsyncMock()
            MockClient.return_value = instance

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get("/products/1/avito-status")

        assert resp.status_code == 502

    @pytest.mark.asyncio
    async def test_avito_status_no_items(self):
        """Avito returns empty items list -> 404."""
        product = _make_product(id=1, account=_make_account())
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = product

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        app = _make_app(mock_db)

        with patch("app.routes.products.AvitoClient") as MockClient:
            instance = AsyncMock()
            instance.get_items_info = AsyncMock(return_value=[])
            instance.close = AsyncMock()
            MockClient.return_value = instance

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get("/products/1/avito-status")

        assert resp.status_code == 404


# ── POST /products/bulk-categories ──────────────────────────────────


class TestBulkCategories:
    @pytest.mark.asyncio
    async def test_bulk_categories_no_ids(self):
        """Empty product_ids returns 400."""
        mock_db = _empty_db()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/products/bulk-categories", json={"product_ids": []})

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_bulk_categories_updates(self):
        """Bulk categories updates matching products."""
        p1 = _make_product(id=1, status="draft", category=None)
        p2 = _make_product(id=2, status="imported", category=None)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [p1, p2]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/products/bulk-categories", json={
                "product_ids": [1, 2],
                "category": "Одежда, обувь, аксессуары",
                "goods_type": "Мужская обувь",
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["updated"] == 2
        assert p1.category == "Одежда, обувь, аксессуары"
        assert p1.goods_type == "Мужская обувь"


# ── POST /products/bulk-descriptions ────────────────────────────────


class TestBulkDescriptions:
    @pytest.mark.asyncio
    async def test_bulk_descriptions_no_ids(self):
        """Empty product_ids returns 400."""
        mock_db = _empty_db()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/products/bulk-descriptions", json={"product_ids": []})

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_bulk_descriptions_generates(self):
        """Bulk descriptions generates descriptions from product fields."""
        p = _make_product(id=1, title="Nike Air Max", brand="Nike", size="42", color="Black")
        p.material = None
        p.condition = None
        p.goods_type = "Мужская обувь"
        p.subcategory = "Кроссовки и кеды"
        p.goods_subtype = "Кроссовки"

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [p]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/products/bulk-descriptions", json={"product_ids": [1]})

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["updated"] == 1
        assert "Nike Air Max" in data["items"][0]["description"]
        assert "Бренд: Nike" in data["items"][0]["description"]


# ── POST /products/bulk-activate ────────────────────────────────────


class TestBulkActivate:
    @pytest.mark.asyncio
    async def test_bulk_activate_no_ids(self):
        """Empty product_ids returns 400."""
        mock_db = _empty_db()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/products/bulk-activate", json={"product_ids": []})

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_bulk_activate_ready_products(self):
        """Products with all required fields are activated."""
        p = _make_product(id=1, status="draft")

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [p]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/products/bulk-activate", json={"product_ids": [1]})

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["activated"] == 1
        assert data["skipped"] == 0
        assert p.status == "active"

    @pytest.mark.asyncio
    async def test_bulk_activate_skips_incomplete(self):
        """Products missing required fields are skipped."""
        p = _make_product(id=1, status="draft", goods_type=None, description=None)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [p]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/products/bulk-activate", json={"product_ids": [1]})

        assert resp.status_code == 200
        data = resp.json()
        assert data["activated"] == 0
        assert data["skipped"] == 1


# ── GET /products (product list page) ─────────────────────────────


class TestProductListPage:
    @pytest.mark.asyncio
    async def test_product_list_renders(self):
        """GET /products returns HTML with product list template."""
        product = _make_product(id=1, title="Nike Air Max")
        account = _make_account(id=1, name="Shop1")

        call_count = [0]

        def make_result(*args, **kwargs):
            call_count[0] += 1
            r = MagicMock()
            if call_count[0] == 1:  # products query
                r.scalars.return_value.all.return_value = [product]
            else:  # accounts query
                r.scalars.return_value.all.return_value = [account]
            return r

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=make_result)
        app = _make_app(mock_db)

        with patch("app.routes.products.templates") as mock_templates:
            from fastapi.responses import HTMLResponse
            mock_templates.TemplateResponse.return_value = HTMLResponse("<html>ok</html>")

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get("/products")

        assert resp.status_code == 200
        mock_templates.TemplateResponse.assert_called_once()
        call_args = mock_templates.TemplateResponse.call_args
        assert call_args[0][0] == "products/list.html"
        ctx = call_args[0][1]
        assert ctx["products"] == [product]
        assert ctx["accounts"] == [account]
        assert ctx["selected_account_id"] is None

    @pytest.mark.asyncio
    async def test_product_list_with_account_filter(self):
        """GET /products?account_id=2 passes filter to template."""
        call_count = [0]

        def make_result(*args, **kwargs):
            call_count[0] += 1
            r = MagicMock()
            r.scalars.return_value.all.return_value = []
            return r

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=make_result)
        app = _make_app(mock_db)

        with patch("app.routes.products.templates") as mock_templates:
            from fastapi.responses import HTMLResponse
            mock_templates.TemplateResponse.return_value = HTMLResponse("<html>ok</html>")

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get("/products?account_id=2")

        assert resp.status_code == 200
        ctx = mock_templates.TemplateResponse.call_args[0][1]
        assert ctx["selected_account_id"] == 2


# ── POST /products/import-from-avito ──────────────────────────────


class TestImportFromAvito:
    @pytest.mark.asyncio
    async def test_import_missing_account_id(self):
        """Import without account_id returns 400."""
        mock_db = _empty_db()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/products/import-from-avito", json={})

        assert resp.status_code == 400
        assert resp.json()["ok"] is False

    @pytest.mark.asyncio
    async def test_import_account_not_found(self):
        """Import with non-existent account returns 404."""
        mock_db = _empty_db()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/products/import-from-avito", json={"account_id": 999})

        assert resp.status_code == 404
        assert resp.json()["ok"] is False

    @pytest.mark.asyncio
    async def test_import_avito_api_error(self):
        """Import with Avito API error returns 502."""
        account = _make_account(id=1)
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=account)
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        with patch("app.routes.products.AvitoClient") as MockClient:
            instance = AsyncMock()
            instance.get_user_items = AsyncMock(side_effect=Exception("API error"))
            instance.close = AsyncMock()
            MockClient.return_value = instance

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/products/import-from-avito", json={"account_id": 1})

        assert resp.status_code == 502

    @pytest.mark.asyncio
    async def test_import_success(self):
        """Successful import creates products and returns counts."""
        account = _make_account(id=1)

        existing_result = MagicMock()
        existing_result.all.return_value = []  # no existing avito_ids

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=account)
        mock_db.execute = AsyncMock(return_value=existing_result)
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        avito_items = [
            {"id": 100, "title": "Item 1", "price": 5000, "url": "https://avito.ru/1", "category": {"name": "Shoes"}},
            {"id": 200, "title": "Item 2", "price": 3000, "url": "https://avito.ru/2", "category": {}},
        ]

        with patch("app.routes.products.AvitoClient") as MockClient:
            instance = AsyncMock()
            instance.get_user_items = AsyncMock(return_value=avito_items)
            instance.close = AsyncMock()
            MockClient.return_value = instance

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/products/import-from-avito", json={"account_id": 1})

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["imported"] == 2
        assert data["skipped"] == 0
        assert data["total"] == 2

    @pytest.mark.asyncio
    async def test_import_skips_duplicates(self):
        """Import skips items whose avito_id already exists in DB."""
        account = _make_account(id=1)

        existing_result = MagicMock()
        existing_result.all.return_value = [(100,)]  # avito_id=100 already exists

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=account)
        mock_db.execute = AsyncMock(return_value=existing_result)
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        avito_items = [
            {"id": 100, "title": "Duplicate", "price": 5000},
            {"id": 200, "title": "New item", "price": 3000},
        ]

        with patch("app.routes.products.AvitoClient") as MockClient:
            instance = AsyncMock()
            instance.get_user_items = AsyncMock(return_value=avito_items)
            instance.close = AsyncMock()
            MockClient.return_value = instance

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/products/import-from-avito", json={"account_id": 1})

        assert resp.status_code == 200
        data = resp.json()
        assert data["imported"] == 1
        assert data["skipped"] == 1


# ── GET /products/{id} (detail page) ──────────────────────────────


class TestProductDetailPage:
    @pytest.mark.asyncio
    async def test_detail_not_found(self):
        """GET /products/999 returns 404 when product not found."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/products/999")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_detail_renders(self):
        """GET /products/1 renders detail template with product context."""
        product = _make_product(id=1, title="Nike Air Max")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = product

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        app = _make_app(mock_db)

        with patch("app.routes.products.templates") as mock_templates:
            from fastapi.responses import HTMLResponse
            mock_templates.TemplateResponse.return_value = HTMLResponse("<html>detail</html>")

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get("/products/1")

        assert resp.status_code == 200
        call_args = mock_templates.TemplateResponse.call_args
        assert call_args[0][0] == "products/detail.html"
        ctx = call_args[0][1]
        assert ctx["product"] == product


# ── GET /products/new (new product page) ───────────────────────────


class TestProductNewPage:
    @pytest.mark.asyncio
    async def test_new_page_renders(self):
        """GET /products/new renders form template."""
        account = _make_account(id=1)
        model_obj = MagicMock()
        model_obj.id = 1
        model_obj.name = "Air Max 90"

        call_count = [0]

        def make_result(*args, **kwargs):
            call_count[0] += 1
            r = MagicMock()
            if call_count[0] == 1:  # accounts query
                r.scalars.return_value.all.return_value = [account]
            elif call_count[0] == 2:  # models query
                r.scalars.return_value.all.return_value = [model_obj]
            else:  # catalog queries
                r.scalars.return_value.all.return_value = []
                r.all.return_value = []
            return r

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=make_result)
        app = _make_app(mock_db)

        with patch("app.routes.products.templates") as mock_templates, \
             patch("app.routes.products.get_catalog", new_callable=AsyncMock) as mock_catalog:
            from fastapi.responses import HTMLResponse
            mock_templates.TemplateResponse.return_value = HTMLResponse("<html>form</html>")
            mock_catalog.return_value = {"categories": [], "goods_types": {}, "apparels": {}, "goods_subtypes": {}, "conditions": []}

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get("/products/new")

        assert resp.status_code == 200
        call_args = mock_templates.TemplateResponse.call_args
        assert call_args[0][0] == "products/form.html"
        ctx = call_args[0][1]
        assert ctx["product"] is None


# ── GET /products/bulk-edit ────────────────────────────────────────


class TestBulkEditPage:
    @pytest.mark.asyncio
    async def test_bulk_edit_page_renders(self):
        """GET /products/bulk-edit renders bulk edit template."""
        product = _make_product(id=1, status="draft")

        call_count = [0]

        def make_result(*args, **kwargs):
            call_count[0] += 1
            r = MagicMock()
            if call_count[0] == 1:  # products query
                r.scalars.return_value.all.return_value = [product]
            else:  # catalog queries
                r.scalars.return_value.all.return_value = []
                r.all.return_value = []
            return r

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=make_result)
        app = _make_app(mock_db)

        with patch("app.routes.products.templates") as mock_templates, \
             patch("app.routes.products.get_catalog", new_callable=AsyncMock) as mock_catalog:
            from fastapi.responses import HTMLResponse
            mock_templates.TemplateResponse.return_value = HTMLResponse("<html>bulk</html>")
            mock_catalog.return_value = {"categories": [], "goods_types": {}, "apparels": {}, "goods_subtypes": {}, "conditions": []}

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get("/products/bulk-edit")

        assert resp.status_code == 200
        call_args = mock_templates.TemplateResponse.call_args
        assert call_args[0][0] == "products/bulk_edit.html"
        ctx = call_args[0][1]
        assert ctx["products"] == [product]


# ── GET /products/{id}/edit ────────────────────────────────────────


class TestProductEditPage:
    @pytest.mark.asyncio
    async def test_edit_not_found(self):
        """GET /products/999/edit returns 404."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/products/999/edit")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_edit_renders(self):
        """GET /products/1/edit renders form template with product."""
        product = _make_product(id=1)
        account = _make_account(id=1)
        model_obj = MagicMock()
        model_obj.id = 1
        model_obj.name = "Air Max"

        call_count = [0]

        def make_result(*args, **kwargs):
            call_count[0] += 1
            r = MagicMock()
            if call_count[0] == 1:  # product query (now via execute)
                r.scalar_one_or_none.return_value = product
            elif call_count[0] == 2:  # accounts
                r.scalars.return_value.all.return_value = [account]
            elif call_count[0] == 3:  # models
                r.scalars.return_value.all.return_value = [model_obj]
            else:  # catalog + yandex folders
                r.scalars.return_value.all.return_value = []
                r.all.return_value = []
            return r

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=make_result)
        app = _make_app(mock_db)

        with patch("app.routes.products.templates") as mock_templates, \
             patch("app.routes.products.get_catalog", new_callable=AsyncMock) as mock_catalog:
            from fastapi.responses import HTMLResponse
            mock_templates.TemplateResponse.return_value = HTMLResponse("<html>edit</html>")
            mock_catalog.return_value = {"categories": [], "goods_types": {}, "apparels": {}, "goods_subtypes": {}, "conditions": []}

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get("/products/1/edit")

        assert resp.status_code == 200
        call_args = mock_templates.TemplateResponse.call_args
        assert call_args[0][0] == "products/form.html"
        ctx = call_args[0][1]
        assert ctx["product"] == product


    @pytest.mark.asyncio
    async def test_edit_page_renders_200_with_images(self, db):
        """Regression: /products/{id}/edit must load without MissingGreenlet.

        Protects against forgetting selectinload(Product.images) — a bug that
        reached prod on 2026-04-19 and was caught only by manual smoke test.
        """
        from sqlalchemy import text
        from app.models.account import Account
        from app.models.product import Product as ProductModel
        from app.models.product_image import ProductImage

        # Ensure sequence is past any manually-inserted rows
        await db.execute(text(
            "SELECT setval('accounts_id_seq', GREATEST(nextval('accounts_id_seq'), "
            "(SELECT COALESCE(MAX(id), 0) FROM accounts)))"
        ))

        import uuid
        token = uuid.uuid4().hex[:16]
        acc = Account(name=f"EditTest-{token}", client_id=f"c-{token}",
                      client_secret="s", feed_token=token)
        db.add(acc)
        await db.flush()

        p = ProductModel(
            title="Edit Regression Test", price=1000, status="draft",
            account_id=acc.id, description="Test desc",
            category="Одежда, обувь, аксессуары", goods_type="Мужская обувь",
            subcategory="Кроссовки и кеды", goods_subtype="Кроссовки",
            brand="Nike", condition="Новое с биркой",
        )
        db.add(p)
        await db.flush()

        for i in range(2):
            db.add(ProductImage(
                product_id=p.id, url=f"/media/test_{i}.jpg",
                filename=f"test_{i}.jpg", sort_order=i, is_main=(i == 0),
            ))
        await db.flush()

        # Build real app with this DB session (no mocks)
        from fastapi import FastAPI
        from app.db import get_db
        from app.routes.products import router as prod_router
        from app.middleware.auth import BasicAuthMiddleware

        app = FastAPI()
        app.add_middleware(BasicAuthMiddleware)
        app.include_router(prod_router)

        async def override_db():
            yield db

        app.dependency_overrides[get_db] = override_db

        from base64 import b64encode
        from app.config import settings
        creds = b64encode(
            f"{settings.BASIC_AUTH_USER}:{settings.BASIC_AUTH_PASSWORD}".encode()
        ).decode()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
            headers={"Authorization": f"Basic {creds}"},
        ) as client:
            resp = await client.get(f"/products/{p.id}/edit")

        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        assert "MissingGreenlet" not in resp.text


# ── POST /products/new (create product) ────────────────────────────


class TestProductCreate:
    @pytest.mark.asyncio
    async def test_create_product_success(self):
        """POST /products/new creates product and redirects."""
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/products/new", data={
                "title": "Nike Air Max 90",
                "sku": "NKE-001",
                "brand": "Nike",
                "model": "Air Max 90",
                "price": "5000",
                "description": "Great shoes",
                "status": "draft",
                "account_id": "1",
            }, follow_redirects=False)

        assert resp.status_code == 303
        assert "/products/" in resp.headers["location"]
        assert mock_db.add.called

    @pytest.mark.asyncio
    async def test_create_product_validation_error(self):
        """POST /products/new with too-short title returns 400."""
        mock_db = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/products/new", data={
                "title": "ab",  # min_length=3
                "price": "5000",
            }, follow_redirects=False)

        assert resp.status_code == 400
        data = resp.json()
        assert data["ok"] is False

    @pytest.mark.asyncio
    async def test_create_product_with_account_creates_listing(self):
        """POST /products/new with account_id also creates a listing."""
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/products/new", data={
                "title": "Nike Air Max 90",
                "price": "5000",
                "account_id": "1",
            }, follow_redirects=False)

        assert resp.status_code == 303
        # Should call db.add at least twice: product + listing
        assert mock_db.add.call_count >= 2


# ── POST /products/{id}/edit (form update) ─────────────────────────


class TestProductUpdate:
    @pytest.mark.asyncio
    async def test_update_not_found(self):
        """POST /products/999/edit returns 404."""
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/products/999/edit", data={
                "title": "Updated",
                "price": "5000",
            }, follow_redirects=False)

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_update_success(self):
        """POST /products/1/edit updates product and redirects."""
        product = _make_product(id=1)
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=product)
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/products/1/edit", data={
                "title": "Updated Title",
                "price": "7000",
                "status": "active",
                "brand": "Adidas",
                "size": "43",
            }, follow_redirects=False)

        assert resp.status_code == 303
        assert product.title == "Updated Title"
        assert product.price == 7000
        assert product.brand == "Adidas"
        assert product.size == "43"

    @pytest.mark.asyncio
    async def test_update_with_schedule(self):
        """POST /products/1/edit with schedule_enabled sets scheduled status."""
        product = _make_product(id=1, status="draft")
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=product)
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/products/1/edit", data={
                "title": "Scheduled Product",
                "price": "5000",
                "status": "draft",
                "schedule_enabled": "1",
                "scheduled_at": "2026-05-01T10:00",
                "scheduled_account_id": "1",
            }, follow_redirects=False)

        assert resp.status_code == 303
        assert product.status == "scheduled"
        assert product.scheduled_at is not None

    @pytest.mark.asyncio
    async def test_update_invalid_price_sets_none(self):
        """POST /products/1/edit with invalid price sets price to None."""
        product = _make_product(id=1, price=5000)
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=product)
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/products/1/edit", data={
                "title": "Product",
                "price": "not-a-number",
            }, follow_redirects=False)

        assert resp.status_code == 303
        assert product.price is None


# ── DELETE /products/{id}/avito ────────────────────────────────────


class TestDeleteFromAvito:
    @pytest.mark.asyncio
    async def test_delete_avito_not_found(self):
        """DELETE /products/999/avito returns 404."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.delete("/products/999/avito")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_avito_with_avito_id(self):
        """DELETE /products/1/avito with avito_id sets removed, mentions feed."""
        product = _make_product(id=1, avito_id=12345, account=_make_account())
        listing = MagicMock()
        listing.status = "published"
        listing.avito_id = "abc"

        call_count = [0]

        def make_result(*args, **kwargs):
            call_count[0] += 1
            r = MagicMock()
            if call_count[0] == 1:  # product query
                r.scalar_one_or_none.return_value = product
            else:  # listings query
                r.scalars.return_value.all.return_value = [listing]
            return r

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=make_result)
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.delete("/products/1/avito")

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "фида" in data["message"]
        assert product.status == "removed"
        assert listing.status == "draft"

    @pytest.mark.asyncio
    async def test_delete_avito_no_avito_id(self):
        """DELETE /products/1/avito without avito_id — removed from program only."""
        product = _make_product(id=1, avito_id=None)
        product.account = None

        call_count = [0]

        def make_result(*args, **kwargs):
            call_count[0] += 1
            r = MagicMock()
            if call_count[0] == 1:
                r.scalar_one_or_none.return_value = product
            else:
                r.scalars.return_value.all.return_value = []
            return r

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=make_result)
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.delete("/products/1/avito")

        assert resp.status_code == 200
        assert "программы" in resp.json()["message"]


# ── POST /products/{id}/apply-pack ─────────────────────────────────


class TestApplyPack:
    @pytest.mark.asyncio
    async def test_apply_pack_not_found(self):
        """Apply pack to non-existent product returns 404."""
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/products/999/apply-pack", json={"pack_id": 1})

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_apply_pack_missing_pack_id(self):
        """Apply pack without pack_id returns 400."""
        product = _make_product(id=1)
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=product)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/products/1/apply-pack", json={})

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_apply_pack_success(self):
        """Apply pack calls _apply_pack_to_product and returns count."""
        product = _make_product(id=1)
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=product)
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        with patch("app.routes.products._apply_pack_to_product", new_callable=AsyncMock) as mock_apply:
            mock_apply.return_value = 3

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/products/1/apply-pack", json={"pack_id": 5, "uniquify": True})

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["images_added"] == 3
        mock_apply.assert_called_once_with(mock_db, 1, 5, True)


# ── PATCH /products/{id}/pack ──────────────────────────────────────


class TestPatchProductPack:
    @pytest.mark.asyncio
    async def test_patch_pack_not_found(self):
        """PATCH pack on non-existent product returns 404."""
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch("/products/999/pack", json={"pack_id": 1})

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_patch_pack_missing_pack_id(self):
        """PATCH pack without pack_id returns 400."""
        product = _make_product(id=1)
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=product)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch("/products/1/pack", json={})

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_patch_pack_success(self):
        """PATCH pack applies pack and records usage history."""
        product = _make_product(id=1, account_id=1, model_id=5)

        pack_result = MagicMock()
        pack_result.all.return_value = [(10,)]  # model pack IDs

        old_usage_result = MagicMock()
        old_usage_result.scalars.return_value.all.return_value = []  # no old usage

        call_count = [0]

        def make_result(*args, **kwargs):
            call_count[0] += 1
            r = MagicMock()
            if call_count[0] == 1:  # model_packs query
                r.all.return_value = [(10,)]
            elif call_count[0] == 2:  # old_usage query
                r.scalars.return_value.all.return_value = []
            return r

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=product)
        mock_db.execute = AsyncMock(side_effect=make_result)
        mock_db.add = MagicMock()
        mock_db.delete = AsyncMock()
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        with patch("app.routes.products._apply_pack_to_product", new_callable=AsyncMock) as mock_apply:
            mock_apply.return_value = 4

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.patch("/products/1/pack", json={"pack_id": 10})

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["images_added"] == 4
        # Should have added PackUsageHistory record
        assert mock_db.add.called


# ── POST /products/{id}/repost ─────────────────────────────────────


class TestRepostProduct:
    @pytest.mark.asyncio
    async def test_repost_not_found(self):
        """POST /products/999/repost returns 404."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/products/999/repost")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_repost_no_account(self):
        """POST /products/1/repost without account returns 400."""
        product = _make_product(id=1)
        product.account = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = product

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/products/1/repost")

        assert resp.status_code == 400


# ── POST /products/schedule-bulk ───────────────────────────────────


class TestScheduleBulk:
    @pytest.mark.asyncio
    async def test_schedule_bulk_missing_fields(self):
        """Schedule bulk without required fields returns 400."""
        mock_db = _empty_db()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/products/schedule-bulk", json={})

        assert resp.status_code == 400
        assert resp.json()["ok"] is False

    @pytest.mark.asyncio
    async def test_schedule_bulk_invalid_datetime(self):
        """Schedule bulk with bad datetime returns 400."""
        mock_db = _empty_db()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/products/schedule-bulk", json={
                "product_ids": [1],
                "account_id": 1,
                "start_time": "invalid-date",
            })

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_schedule_bulk_not_ready(self):
        """Schedule bulk with unready products returns 400 with not_ready list."""
        product = _make_product(
            id=1, title="Incomplete", description=None, price=None,
            category=None, goods_type=None, subcategory=None,
            goods_subtype=None, images=[],
        )

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [product]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/products/schedule-bulk", json={
                "product_ids": [1],
                "account_id": 1,
                "start_time": "2026-05-01T10:00",
            })

        assert resp.status_code == 400
        data = resp.json()
        assert data["ok"] is False
        assert "not_ready" in data
        assert len(data["not_ready"]) == 1

    @pytest.mark.asyncio
    async def test_schedule_bulk_success(self):
        """Schedule bulk creates listings with staggered times."""
        p1 = _make_product(id=1)
        p2 = _make_product(id=2, title="Product 2")

        call_count = [0]

        def make_result(*args, **kwargs):
            call_count[0] += 1
            r = MagicMock()
            if call_count[0] == 1:  # products query
                r.scalars.return_value.all.return_value = [p1, p2]
            else:  # listing queries
                r.scalar_one_or_none.return_value = None  # no existing listing
            return r

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=make_result)
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/products/schedule-bulk", json={
                "product_ids": [1, 2],
                "account_id": 1,
                "start_time": "2026-05-01T10:00",
                "interval_minutes": 30,
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["scheduled"] == 2
        assert len(data["items"]) == 2

    @pytest.mark.asyncio
    async def test_schedule_bulk_product_not_found(self):
        """Schedule bulk with non-existent product_id returns not_ready."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []  # no products found

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/products/schedule-bulk", json={
                "product_ids": [999],
                "account_id": 1,
                "start_time": "2026-05-01T10:00",
            })

        assert resp.status_code == 400
        data = resp.json()
        assert "not_ready" in data
        assert data["not_ready"][0]["problems"] == ["Товар не найден"]


# ── Duplicate preserves template link (integration) ────────────────


class TestDuplicatePreservesTemplateLink:
    @pytest.mark.asyncio
    async def test_duplicate_preserves_template_link(self, isolated_db):
        """Regression: duplicate_product must copy use_custom_description, description_template_id, model_id."""
        import uuid
        from sqlalchemy import text, select as sa_select
        from base64 import b64encode
        from app.config import settings
        from app.models.account import Account
        from app.models.model import Model
        from app.models.description_template import DescriptionTemplate
        from app.models.product import Product as ProductModel

        db = isolated_db
        await db.execute(text(
            "SELECT setval('accounts_id_seq', GREATEST(nextval('accounts_id_seq'), "
            "(SELECT COALESCE(MAX(id), 0) FROM accounts)))"
        ))
        token = uuid.uuid4().hex[:8]
        acc = Account(name=f"DupTest-{token}", client_id=f"c-{token}",
                      client_secret="s", feed_token=token)
        db.add(acc)
        await db.flush()

        model = Model(name=f"DupModel-{token}", brand="TestBrand")
        db.add(model)
        await db.flush()

        tpl = DescriptionTemplate(name=f"DupTpl-{token}", body="tpl body")
        db.add(tpl)
        await db.flush()

        source = ProductModel(
            title="Source Product", description="Custom desc", price=3000,
            status="draft", account_id=acc.id, model_id=model.id,
            category="Одежда, обувь, аксессуары", goods_type="Мужская обувь",
            subcategory="Кроссовки", goods_subtype="Кроссовки",
            brand="TestBrand", condition="Новое с биркой",
            use_custom_description=True,
            description_template_id=tpl.id,
        )
        db.add(source)
        await db.flush()

        from fastapi import FastAPI
        from app.db import get_db
        from app.routes.products import router as prod_router
        from app.middleware.auth import BasicAuthMiddleware

        app = FastAPI()
        app.add_middleware(BasicAuthMiddleware)
        app.include_router(prod_router)

        async def override_db():
            yield db

        app.dependency_overrides[get_db] = override_db

        creds = b64encode(
            f"{settings.BASIC_AUTH_USER}:{settings.BASIC_AUTH_PASSWORD}".encode()
        ).decode()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
            headers={"Authorization": f"Basic {creds}"},
            follow_redirects=False,
        ) as client:
            resp = await client.post(f"/products/{source.id}/duplicate")

        assert resp.status_code == 303

        result = await db.execute(
            sa_select(ProductModel)
            .where(ProductModel.title == "Source Product (копия)")
            .order_by(ProductModel.id.desc())
        )
        copy = result.scalar_one_or_none()
        assert copy is not None
        assert copy.description_template_id == tpl.id
        assert copy.use_custom_description is True
        assert copy.model_id == model.id
        assert copy.description == "Custom desc"
