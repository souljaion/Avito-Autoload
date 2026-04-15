"""Tests for models routes (unit tests with mock DB)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from httpx import AsyncClient, ASGITransport

from app.db import get_db
from app.routes.models import router


def _make_app(mock_db):
    app = FastAPI()
    app.include_router(router)

    async def override_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_db
    return app


def _empty_db():
    """Mock DB that returns empty results for all queries."""
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_result.scalars.return_value.unique.return_value.all.return_value = []
    mock_result.scalar_one_or_none.return_value = None

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.get = AsyncMock(return_value=None)
    return mock_db


def _make_account(id=1, name="TestAccount", avito_sync_minute=None):
    acc = MagicMock()
    acc.id = id
    acc.name = name
    acc.avito_sync_minute = avito_sync_minute
    return acc


def _make_image(id=1, url="/media/products/1/img.jpg", filename="img.jpg",
                sort_order=0, is_main=True):
    img = MagicMock()
    img.id = id
    img.url = url
    img.filename = filename
    img.sort_order = sort_order
    img.is_main = is_main
    return img


def _make_product(id=1, account_id=1, model_id=1, status="active",
                  title="Nike Air Max", price=5000, avito_id=None,
                  scheduled_at=None, variant_id=None):
    p = MagicMock()
    p.id = id
    p.account_id = account_id
    p.model_id = model_id
    p.status = status
    p.title = title
    p.price = price
    p.avito_id = avito_id
    p.scheduled_at = scheduled_at
    p.published_at = None
    p.variant_id = variant_id
    p.sku = "SKU001"
    p.brand = "Nike"
    p.model = "Air Max"
    p.category = "Одежда, обувь, аксессуары"
    p.subcategory = "Кроссовки и кеды"
    p.goods_type = "Мужская обувь"
    p.goods_subtype = "Кроссовки"
    p.size = "42"
    p.color = "Белый"
    p.material = None
    p.condition = "Новое с биркой"
    p.description = "Test description"
    p.use_custom_description = False
    p.image_url = None
    p.extra = {}
    p.images = [_make_image()]
    p.account = _make_account(id=account_id)
    return p


def _make_photo_pack(id=1, name="Pack 1", images=None):
    pack = MagicMock()
    pack.id = id
    pack.name = name
    pack.images = images or [_make_image(url="/media/packs/1/photo.jpg")]
    return pack


def _make_model(id=1, name="Air Max 90", brand="Nike", description="Sneakers",
                products=None, photo_packs=None):
    m = MagicMock()
    m.id = id
    m.name = name
    m.brand = brand
    m.description = description
    m.category = "Одежда, обувь, аксессуары"
    m.subcategory = "Кроссовки и кеды"
    m.goods_type = "Мужская обувь"
    m.goods_subtype = "Кроссовки"
    m.products = products or []
    m.photo_packs = photo_packs or []
    return m


# ── GET /models (model_list) ────────────────────────────────────────

class TestModelList:
    @pytest.mark.asyncio
    async def test_empty_list(self):
        """Empty DB returns 200 with HTML."""
        mock_db = _empty_db()
        app = _make_app(mock_db)

        with patch("app.routes.models.templates") as mock_templates:
            mock_templates.TemplateResponse.return_value = HTMLResponse("<html></html>")
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/models")

            assert resp.status_code == 200
            call_args = mock_templates.TemplateResponse.call_args
            ctx = call_args[0][1]
            assert ctx["matrix"] == []
            assert ctx["accounts"] == []

    @pytest.mark.asyncio
    async def test_list_with_models(self):
        """Model list renders models with matrix data."""
        acc = _make_account(id=1, name="Zulla")
        product = _make_product(id=10, account_id=1, model_id=1)
        pack = _make_photo_pack(id=1, name="Pack A")
        model = _make_model(id=1, products=[product], photo_packs=[pack])

        call_count = 0

        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # Models query
                result.scalars.return_value.unique.return_value.all.return_value = [model]
            else:
                # Accounts query
                result.scalars.return_value.all.return_value = [acc]
            return result

        mock_db = AsyncMock()
        mock_db.execute = mock_execute
        app = _make_app(mock_db)

        with patch("app.routes.models.templates") as mock_templates:
            mock_templates.TemplateResponse.return_value = HTMLResponse("<html></html>")
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/models")

            assert resp.status_code == 200
            ctx = mock_templates.TemplateResponse.call_args[0][1]
            assert len(ctx["matrix"]) == 1
            assert ctx["matrix"][0]["model"] is model
            assert len(ctx["accounts"]) == 1
            assert "Nike" in ctx["brands"]


# ── POST /models (model_create) ─────────────────────────────────────

class TestModelCreate:
    @pytest.mark.asyncio
    async def test_create_json_response(self):
        """Create model returns JSON when Accept: application/json."""
        mock_db = AsyncMock()
        mock_db.commit = AsyncMock()

        # After db.add + commit, model.id should be set
        def mock_add(obj):
            obj.id = 42

        mock_db.add = mock_add
        app = _make_app(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/models",
                data={"name": "Jordan 1", "brand": "Nike", "description": "Classic"},
                headers={"accept": "application/json"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["name"] == "Jordan 1"
        assert data["brand"] == "Nike"

    @pytest.mark.asyncio
    async def test_create_redirect(self):
        """Create model redirects when Accept is not JSON."""
        mock_db = AsyncMock()
        mock_db.commit = AsyncMock()

        def mock_add(obj):
            obj.id = 7

        mock_db.add = mock_add
        app = _make_app(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            follow_redirects=False,
        ) as client:
            resp = await client.post(
                "/models",
                data={"name": "Yeezy 350", "brand": "Adidas"},
            )

        assert resp.status_code == 303
        assert "/models/7" in resp.headers["location"]

    @pytest.mark.asyncio
    async def test_create_empty_name_400(self):
        """Empty name returns 400 validation error."""
        mock_db = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/models", data={"name": ""})

        assert resp.status_code == 400
        assert resp.json()["ok"] is False


# ── GET /models/{id} (model_detail) ─────────────────────────────────

class TestModelDetail:
    @pytest.mark.asyncio
    async def test_detail_not_found(self):
        """Missing model returns 404."""
        mock_db = _empty_db()
        app = _make_app(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/models/999")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_detail_found(self):
        """Existing model returns 200 with template."""
        model = _make_model(id=5, products=[_make_product()], photo_packs=[_make_photo_pack()])

        call_count = 0

        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # Model query
                result.scalar_one_or_none.return_value = model
            elif call_count == 2:
                # Unassigned products query
                result.scalars.return_value.all.return_value = []
            elif call_count == 3:
                # Accounts query
                result.scalars.return_value.all.return_value = [_make_account()]
            else:
                # get_catalog queries (AvitoCategory root + all)
                result.scalar_one_or_none.return_value = None
                result.scalars.return_value.all.return_value = []
            return result

        mock_db = AsyncMock()
        mock_db.execute = mock_execute
        app = _make_app(mock_db)

        with patch("app.routes.models.templates") as mock_templates:
            mock_templates.TemplateResponse.return_value = HTMLResponse("<html></html>")
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/models/5")

            assert resp.status_code == 200
            ctx = mock_templates.TemplateResponse.call_args[0][1]
            assert ctx["model"] is model


# ── POST /models/{id}/add-variant ────────────────────────────────────

class TestAddVariant:
    @pytest.mark.asyncio
    async def test_add_variant_missing_model(self):
        """404 when model not found."""
        mock_db = _empty_db()
        app = _make_app(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/models/999/add-variant",
                json={"product_ids": [1, 2]},
            )

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_add_variant_success(self):
        """Add variant links products to model."""
        model = _make_model(id=1)
        p1 = _make_product(id=10)
        p2 = _make_product(id=11)

        async def mock_execute(stmt, *args, **kwargs):
            result = MagicMock()
            result.scalars.return_value.all.return_value = [p1, p2]
            return result

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=model)
        mock_db.execute = mock_execute
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/models/1/add-variant",
                json={"product_ids": [10, 11]},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["added"] == 2
        assert p1.model_id == 1
        assert p2.model_id == 1

    @pytest.mark.asyncio
    async def test_add_variant_no_ids_400(self):
        """Missing product_ids returns 400."""
        model = _make_model(id=1)
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=model)
        app = _make_app(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/models/1/add-variant",
                json={},
            )

        assert resp.status_code == 400


# ── POST /models/{id}/copy-variant ───────────────────────────────────

class TestCopyVariant:
    @pytest.mark.asyncio
    async def test_copy_variant_missing_model(self):
        """404 when model not found."""
        mock_db = _empty_db()
        app = _make_app(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/models/999/copy-variant",
                json={"product_id": 1, "account_id": 2},
            )

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_copy_variant_missing_source(self):
        """404 when source product not found."""
        model = _make_model(id=1)

        async def mock_execute(stmt, *args, **kwargs):
            result = MagicMock()
            result.scalar_one_or_none.return_value = None
            return result

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=model)
        mock_db.execute = mock_execute
        mock_db.commit = AsyncMock()
        mock_db.flush = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/models/1/copy-variant",
                json={"product_id": 99, "account_id": 2},
            )

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_copy_variant_success(self):
        """Successful copy returns new product id."""
        model = _make_model(id=1)
        source = _make_product(id=10)
        source.images = [_make_image()]
        source.extra = {"key": "val"}

        added_objects = []

        async def mock_execute(stmt, *args, **kwargs):
            result = MagicMock()
            result.scalar_one_or_none.return_value = source
            return result

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=model)
        mock_db.execute = mock_execute
        mock_db.commit = AsyncMock()
        mock_db.flush = AsyncMock()

        def track_add(obj):
            added_objects.append(obj)
            if hasattr(obj, 'id') and obj.id is None:
                obj.id = 100

        mock_db.add = track_add
        app = _make_app(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/models/1/copy-variant",
                json={"product_id": 10, "account_id": 2},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["new_product_id"] == 100


# ── POST /models/{id}/detach-variant ─────────────────────────────────

class TestDetachVariant:
    @pytest.mark.asyncio
    async def test_detach_wrong_model(self):
        """404 when product doesn't belong to this model."""
        product = _make_product(id=10, model_id=999)
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=product)
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/models/1/detach-variant",
                json={"product_id": 10},
            )

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_detach_success(self):
        """Detach sets model_id to None."""
        product = _make_product(id=10, model_id=1)
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=product)
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/models/1/detach-variant",
                json={"product_id": 10},
            )

        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert product.model_id is None


# ── POST /models/{id}/update-name ────────────────────────────────────

class TestUpdateName:
    @pytest.mark.asyncio
    async def test_update_name_not_found(self):
        """404 when model not found."""
        mock_db = _empty_db()
        app = _make_app(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/models/999/update-name",
                json={"name": "New Name"},
            )

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_update_name_empty_400(self):
        """Empty name returns 400."""
        model = _make_model(id=1)
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=model)
        app = _make_app(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/models/1/update-name",
                json={"name": "  "},
            )

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_update_name_success(self):
        """Successful name update."""
        model = _make_model(id=1, name="Old Name")
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=model)
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/models/1/update-name",
                json={"name": "New Name", "brand": "Adidas"},
            )

        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert model.name == "New Name"
        assert model.brand == "Adidas"


# ── GET /models/{id}/info ────────────────────────────────────────────

class TestModelInfo:
    @pytest.mark.asyncio
    async def test_info_not_found(self):
        """404 when model not found."""
        mock_db = _empty_db()
        app = _make_app(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/models/999/info")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_info_success(self):
        """Returns model info as JSON."""
        model = _make_model(id=5, name="Dunk Low", brand="Nike", description="Classic shoe")
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=model)
        app = _make_app(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/models/5/info")

        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Dunk Low"
        assert data["brand"] == "Nike"
        assert data["description"] == "Classic shoe"


# ── PATCH /models/{id} ──────────────────────────────────────────────

class TestPatchModel:
    @pytest.mark.asyncio
    async def test_patch_not_found(self):
        """404 when model not found."""
        mock_db = _empty_db()
        app = _make_app(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.patch("/models/999", json={"name": "X"})

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_patch_empty_name_400(self):
        """Empty name returns 400."""
        model = _make_model(id=1)
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=model)
        app = _make_app(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.patch("/models/1", json={"name": ""})

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_patch_success(self):
        """Successful patch updates fields."""
        model = _make_model(id=1, name="Old", brand="Old Brand")
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=model)
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.patch(
                "/models/1",
                json={"name": "New", "brand": "Puma", "category": "Test Cat"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["name"] == "New"
        assert model.name == "New"
        assert model.brand == "Puma"
        assert model.category == "Test Cat"


# ── DELETE /models/{id} ─────────────────────────────────────────────

class TestDeleteModel:
    @pytest.mark.asyncio
    async def test_delete_not_found(self):
        """404 when model not found."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        app = _make_app(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.delete("/models/999")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_success(self):
        """Delete detaches products and removes model."""
        p1 = _make_product(id=10, model_id=1)
        p2 = _make_product(id=11, model_id=1)
        model = _make_model(id=1, products=[p1, p2])

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = model

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.delete = AsyncMock()
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.delete("/models/1")

        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        # Products should be detached
        assert p1.model_id is None
        assert p2.model_id is None
        mock_db.delete.assert_awaited_once_with(model)


# ── GET /models/{id}/accounts-status ─────────────────────────────────

class TestAccountsStatus:
    @pytest.mark.asyncio
    async def test_accounts_status_not_found(self):
        """404 when model not found."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        app = _make_app(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/models/999/accounts-status")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_accounts_status_success(self):
        """Returns per-account status items."""
        acc1 = _make_account(id=1, name="Shop1")
        acc2 = _make_account(id=2, name="Shop2")
        product = _make_product(id=10, account_id=1, model_id=1, status="active", avito_id=12345)
        model = _make_model(id=1, products=[product], photo_packs=[])

        call_count = 0

        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # Model query
                result.scalar_one_or_none.return_value = model
            elif call_count == 2:
                # Accounts query
                result.scalars.return_value.all.return_value = [acc1, acc2]
            else:
                # Stats queries (window, baseline, totals, today, yesterday)
                # and PackUsageHistory — all return empty
                result.all.return_value = []
                result.scalars.return_value.all.return_value = []
            return result

        mock_db = AsyncMock()
        mock_db.execute = mock_execute
        app = _make_app(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/models/1/accounts-status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert len(data["items"]) == 2
        # First account has product
        item1 = data["items"][0]
        assert item1["account_id"] == 1
        assert item1["product_id"] == 10
        assert item1["status"] == "active"
        # Second account has no product
        item2 = data["items"][1]
        assert item2["account_id"] == 2
        assert item2["product_id"] is None
        assert item2["status"] == "none"


# ── POST /models/{id}/create-variant ─────────────────────────────────

class TestCreateVariant:
    @pytest.mark.asyncio
    async def test_create_variant_not_found(self):
        """404 when model not found."""
        mock_db = _empty_db()
        app = _make_app(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            follow_redirects=False,
        ) as client:
            resp = await client.post(
                "/models/999/create-variant",
                data={"title": "Test", "price": "5000"},
            )

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_create_variant_success(self):
        """Successful variant creation redirects."""
        model = _make_model(id=3)
        added_objects = []

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=model)
        mock_db.commit = AsyncMock()
        mock_db.flush = AsyncMock()

        def track_add(obj):
            added_objects.append(obj)
            if hasattr(obj, 'id') and obj.id is None:
                obj.id = 50

        mock_db.add = track_add
        app = _make_app(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            follow_redirects=False,
        ) as client:
            resp = await client.post(
                "/models/3/create-variant",
                data={
                    "title": "Nike Dunk Low",
                    "brand": "Nike",
                    "price": "8000",
                    "size": "43",
                    "color": "Black",
                    "account_id": "1",
                },
            )

        assert resp.status_code == 303
        assert "/models/3" in resp.headers["location"]
        # Should have added Product + Listing
        assert len(added_objects) >= 2


# ── Helper: pack image with file_path ──────────────────────────────
def _make_pack_image(id=1, file_path="/media/packs/1/photo.jpg", url="/media/packs/1/photo.jpg",
                     sort_order=0):
    img = MagicMock()
    img.id = id
    img.file_path = file_path
    img.url = url
    img.sort_order = sort_order
    return img


def _make_photo_pack_with_files(id=1, name="Pack 1", images=None):
    pack = MagicMock()
    pack.id = id
    pack.name = name
    pack.images = [_make_pack_image()] if images is None else images
    return pack


def _make_usage_record(pack_id=1, account_id=1, uniquified=False):
    u = MagicMock()
    u.pack_id = pack_id
    u.account_id = account_id
    u.uniquified = uniquified
    return u


# ── POST /models/{id}/create-all-preview ────────────────────────────

class TestCreateAllPreview:
    @pytest.mark.asyncio
    async def test_preview_model_not_found(self):
        """404 when model not found."""
        call_count = 0

        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            result.scalar_one_or_none.return_value = None
            result.scalars.return_value.all.return_value = []
            return result

        mock_db = AsyncMock()
        mock_db.execute = mock_execute
        app = _make_app(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/models/999/create-all-preview")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_preview_no_packs_with_photos(self):
        """400 when no photo packs have images."""
        empty_pack = _make_photo_pack_with_files(id=1, name="Empty", images=[])
        model = _make_model(id=1, products=[], photo_packs=[empty_pack])

        call_count = 0

        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = model
            else:
                result.scalars.return_value.all.return_value = []
            return result

        mock_db = AsyncMock()
        mock_db.execute = mock_execute
        app = _make_app(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/models/1/create-all-preview")

        assert resp.status_code == 400
        assert "фотопаков" in resp.json()["error"]

    @pytest.mark.asyncio
    async def test_preview_success_with_skip_and_create(self):
        """Preview returns items with skip for existing accounts and create for new."""
        acc1 = _make_account(id=1, name="Existing")
        acc2 = _make_account(id=2, name="New")
        pack = _make_photo_pack_with_files(id=10, name="Pack A")
        # product exists on acc1
        existing_product = _make_product(id=5, account_id=1, model_id=1, status="active")
        model = _make_model(id=1, products=[existing_product], photo_packs=[pack])

        call_count = 0

        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = model
            elif call_count == 2:
                result.scalars.return_value.all.return_value = [acc1, acc2]
            else:
                # PackUsageHistory query
                result.scalars.return_value.all.return_value = []
            return result

        mock_db = AsyncMock()
        mock_db.execute = mock_execute
        app = _make_app(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/models/1/create-all-preview")

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert len(data["items"]) == 2
        assert data["items"][0]["action"] == "skip"
        assert data["items"][1]["action"] == "create"
        assert len(data["packs"]) == 1

    @pytest.mark.asyncio
    async def test_preview_with_usage_history_sets_uniquify(self):
        """Preview marks uniquify=True when pack was already used for the account."""
        acc1 = _make_account(id=1, name="Shop1")
        pack = _make_photo_pack_with_files(id=10, name="Pack A")
        model = _make_model(id=1, products=[], photo_packs=[pack])
        usage = _make_usage_record(pack_id=10, account_id=1)

        call_count = 0

        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = model
            elif call_count == 2:
                result.scalars.return_value.all.return_value = [acc1]
            else:
                result.scalars.return_value.all.return_value = [usage]
            return result

        mock_db = AsyncMock()
        mock_db.execute = mock_execute
        app = _make_app(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/models/1/create-all-preview")

        assert resp.status_code == 200
        data = resp.json()
        assert data["items"][0]["uniquify"] is True
        assert data["items"][0]["action"] == "create"


# ── POST /models/{id}/create-all-listings ────────────────────────────

class TestCreateAllListings:
    @pytest.mark.asyncio
    async def test_create_all_model_not_found(self):
        """404 when model not found."""
        call_count = 0

        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            result.scalar_one_or_none.return_value = None
            result.scalars.return_value.all.return_value = []
            return result

        mock_db = AsyncMock()
        mock_db.execute = mock_execute
        app = _make_app(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/models/999/create-all-listings",
                json={"items": [{"account_id": 1, "pack_id": 1}]},
            )

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_create_all_success(self):
        """Creates products for accounts, skips existing."""
        pack = _make_photo_pack_with_files(id=10, name="Pack A")
        existing_product = _make_product(id=5, account_id=1, model_id=1, status="active")
        model = _make_model(id=1, name="Air Max", brand="Nike",
                            products=[existing_product], photo_packs=[pack])

        acc_obj = _make_account(id=2, name="NewShop")
        call_count = 0
        added_objects = []

        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # Model query
                result.scalar_one_or_none.return_value = model
            elif call_count == 2:
                # AccountDescriptionTemplate query
                result.scalars.return_value.all.return_value = []
            else:
                # PackUsageHistory check
                result.scalar_one_or_none.return_value = None
            return result

        mock_db = AsyncMock()
        mock_db.execute = mock_execute
        mock_db.commit = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.get = AsyncMock(return_value=acc_obj)

        def track_add(obj):
            added_objects.append(obj)
            if hasattr(obj, "id") and obj.id is None:
                obj.id = 100

        mock_db.add = track_add
        app = _make_app(mock_db)

        mock_settings = MagicMock(MEDIA_DIR="/tmp/media")
        with patch("os.path.isfile", return_value=True), \
             patch("os.makedirs"), \
             patch("shutil.copy2"), \
             patch("app.config.settings", mock_settings):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/models/1/create-all-listings",
                    json={"items": [
                        {"account_id": 1, "pack_id": 10},
                        {"account_id": 2, "pack_id": 10},
                    ]},
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["created"] == 1
        assert data["skipped"] == 1
        # Verify the created item
        created_items = [i for i in data["items"] if i["status"] == "created"]
        assert len(created_items) == 1
        assert created_items[0]["account_id"] == 2

    @pytest.mark.asyncio
    async def test_create_all_skip_flag(self):
        """Items marked skip=True are skipped."""
        pack = _make_photo_pack_with_files(id=10, name="Pack A")
        model = _make_model(id=1, name="Air Max", brand="Nike",
                            products=[], photo_packs=[pack])

        call_count = 0

        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = model
            else:
                result.scalars.return_value.all.return_value = []
            return result

        mock_db = AsyncMock()
        mock_db.execute = mock_execute
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/models/1/create-all-listings",
                json={"items": [
                    {"account_id": 1, "pack_id": 10, "skip": True},
                ]},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["created"] == 0
        assert data["skipped"] == 1


# ── POST /models/schedule-matrix ─────────────────────────────────────

class TestScheduleMatrix:
    @pytest.mark.asyncio
    async def test_schedule_missing_fields(self):
        """400 when items or start_time missing."""
        mock_db = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/models/schedule-matrix",
                json={"items": []},
            )

        assert resp.status_code == 400
        assert "Missing" in resp.json()["error"]

    @pytest.mark.asyncio
    async def test_schedule_invalid_datetime(self):
        """400 when start_time is invalid."""
        mock_db = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/models/schedule-matrix",
                json={"items": [{"model_id": 1, "account_id": 1}], "start_time": "not-a-date"},
            )

        assert resp.status_code == 400
        assert "Invalid" in resp.json()["error"]

    @pytest.mark.asyncio
    async def test_schedule_success_creates_listings(self):
        """Schedule creates new products and listings."""
        model = _make_model(id=1, name="Dunk", brand="Nike")
        added_objects = []
        call_count = 0

        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # AccountDescriptionTemplate
                result.scalars.return_value.all.return_value = []
            else:
                # Product lookup or Listing lookup
                result.scalar_one_or_none.return_value = None
            return result

        mock_db = AsyncMock()
        mock_db.execute = mock_execute
        mock_db.commit = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.get = AsyncMock(return_value=model)

        def track_add(obj):
            added_objects.append(obj)
            if hasattr(obj, "id") and obj.id is None:
                obj.id = 200

        mock_db.add = track_add
        app = _make_app(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/models/schedule-matrix",
                json={
                    "items": [
                        {"model_id": 1, "account_id": 1},
                        {"model_id": 1, "account_id": 2},
                    ],
                    "start_time": "2026-04-15T10:00",
                    "interval_minutes": 30,
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["scheduled"] == 2
        assert len(data["items"]) == 2

    @pytest.mark.asyncio
    async def test_schedule_with_existing_product(self):
        """Schedule uses existing product if product_id provided."""
        product = _make_product(id=50, model_id=1, account_id=1)
        call_count = 0

        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # AccountDescriptionTemplate
                result.scalars.return_value.all.return_value = []
            else:
                # Listing lookup
                result.scalar_one_or_none.return_value = None
            return result

        mock_db = AsyncMock()
        mock_db.execute = mock_execute
        mock_db.commit = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.get = AsyncMock(return_value=product)

        added_objects = []

        def track_add(obj):
            added_objects.append(obj)
            if hasattr(obj, "id") and obj.id is None:
                obj.id = 300

        mock_db.add = track_add
        app = _make_app(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/models/schedule-matrix",
                json={
                    "items": [{"model_id": 1, "account_id": 1, "product_id": 50}],
                    "start_time": "2026-04-15T12:00",
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["scheduled"] == 1


# ── POST /models/{id}/create-one ─────────────────────────────────────

class TestCreateOne:
    @pytest.mark.asyncio
    async def test_create_one_missing_account_id(self):
        """400 when account_id not provided."""
        mock_db = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/models/1/create-one",
                json={},
            )

        assert resp.status_code == 400
        assert "account_id" in resp.json()["error"]

    @pytest.mark.asyncio
    async def test_create_one_model_not_found(self):
        """404 when model not found."""
        call_count = 0

        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            result.scalar_one_or_none.return_value = None
            result.scalars.return_value.all.return_value = []
            return result

        mock_db = AsyncMock()
        mock_db.execute = mock_execute
        app = _make_app(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/models/999/create-one",
                json={"account_id": 1},
            )

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_create_one_existing_product(self):
        """400 when product already exists for this account."""
        existing = _make_product(id=5, account_id=1, model_id=1)
        model = _make_model(id=1, products=[existing], photo_packs=[])

        call_count = 0

        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = model
            else:
                result.scalars.return_value.all.return_value = []
                result.scalar_one_or_none.return_value = None
            return result

        mock_db = AsyncMock()
        mock_db.execute = mock_execute
        app = _make_app(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/models/1/create-one",
                json={"account_id": 1},
            )

        assert resp.status_code == 400
        assert "уже существует" in resp.json()["error"]

    @pytest.mark.asyncio
    async def test_create_one_success_with_pack(self):
        """Creates product with pack images for new account."""
        pack = _make_photo_pack_with_files(id=10, name="Pack A")
        model = _make_model(id=1, name="Jordan 1", brand="Nike",
                            products=[], photo_packs=[pack])

        acc_obj = _make_account(id=3, name="NewShop")
        added_objects = []
        call_count = 0

        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # Model query
                result.scalar_one_or_none.return_value = model
            elif call_count == 2:
                # AccountDescriptionTemplate
                result.scalar_one_or_none.return_value = None
            else:
                # PackUsageHistory
                result.scalars.return_value.all.return_value = []
            return result

        mock_db = AsyncMock()
        mock_db.execute = mock_execute
        mock_db.commit = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.get = AsyncMock(return_value=acc_obj)

        def track_add(obj):
            added_objects.append(obj)
            if hasattr(obj, "id") and obj.id is None:
                obj.id = 150

        mock_db.add = track_add
        app = _make_app(mock_db)

        mock_settings = MagicMock(MEDIA_DIR="/tmp/media")
        with patch("os.path.isfile", return_value=True), \
             patch("os.makedirs"), \
             patch("shutil.copy2") as mock_copy, \
             patch("app.config.settings", mock_settings):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/models/1/create-one",
                    json={"account_id": 3},
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["product_id"] == 150
        assert data["account_name"] == "NewShop"
        mock_copy.assert_called()

    @pytest.mark.asyncio
    async def test_create_one_no_packs(self):
        """Creates product without images when no packs."""
        model = _make_model(id=1, name="Dunk", brand="Nike", products=[], photo_packs=[])

        acc_obj = _make_account(id=2, name="Shop2")
        call_count = 0
        added_objects = []

        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = model
            else:
                result.scalar_one_or_none.return_value = None
                result.scalars.return_value.all.return_value = []
            return result

        mock_db = AsyncMock()
        mock_db.execute = mock_execute
        mock_db.commit = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.get = AsyncMock(return_value=acc_obj)

        def track_add(obj):
            added_objects.append(obj)
            if hasattr(obj, "id") and obj.id is None:
                obj.id = 160

        mock_db.add = track_add
        app = _make_app(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/models/1/create-one",
                json={"account_id": 2},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["product_id"] == 160


# ── GET /models/{id}/accounts-status with pack usage ────────────────

class TestAccountsStatusWithPacks:
    @pytest.mark.asyncio
    async def test_accounts_status_with_pack_usage(self):
        """Returns pack usage info when photo packs have usage history."""
        acc1 = _make_account(id=1, name="Shop1")
        product = _make_product(id=10, account_id=1, model_id=1, status="active")
        pack = _make_photo_pack_with_files(id=20, name="Pack X")
        model = _make_model(id=1, products=[product], photo_packs=[pack])
        usage = _make_usage_record(pack_id=20, account_id=1)

        call_count = 0

        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = model
            elif call_count == 2:
                result.scalars.return_value.all.return_value = [acc1]
            else:
                result.scalars.return_value.all.return_value = [usage]
            return result

        mock_db = AsyncMock()
        mock_db.execute = mock_execute
        app = _make_app(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/models/1/accounts-status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        item = data["items"][0]
        assert item["pack_id"] == 20
        assert item["pack_name"] == "Pack X"
        assert item["status"] == "active"


# ── Additional edge cases ────────────────────────────────────────────

class TestAddVariantBackwardCompat:
    @pytest.mark.asyncio
    async def test_add_variant_single_product_id(self):
        """Backward compat: single product_id works."""
        model = _make_model(id=1)
        p1 = _make_product(id=10)

        async def mock_execute(stmt, *args, **kwargs):
            result = MagicMock()
            result.scalars.return_value.all.return_value = [p1]
            return result

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=model)
        mock_db.execute = mock_execute
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/models/1/add-variant",
                json={"product_id": 10},
            )

        assert resp.status_code == 200
        assert resp.json()["added"] == 1
        assert p1.model_id == 1


class TestCopyVariantMissingFields:
    @pytest.mark.asyncio
    async def test_copy_variant_missing_account_id(self):
        """400 when account_id missing."""
        model = _make_model(id=1)
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=model)
        app = _make_app(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/models/1/copy-variant",
                json={"product_id": 1},
            )

        assert resp.status_code == 400
        assert "account_id" in resp.json()["error"]


class TestDetachVariantNotFound:
    @pytest.mark.asyncio
    async def test_detach_product_not_found(self):
        """404 when product doesn't exist at all."""
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)
        app = _make_app(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/models/1/detach-variant",
                json={"product_id": 999},
            )

        assert resp.status_code == 404


class TestPatchModelCategoryFields:
    @pytest.mark.asyncio
    async def test_patch_category_and_subcategory(self):
        """Patch updates category and subcategory fields."""
        model = _make_model(id=1, name="Test")
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=model)
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.patch(
                "/models/1",
                json={
                    "category": "Электроника",
                    "subcategory": "Телефоны",
                    "goods_type": "Смартфоны",
                    "goods_subtype": "iPhone",
                },
            )

        assert resp.status_code == 200
        assert model.category == "Электроника"
        assert model.subcategory == "Телефоны"
        assert model.goods_type == "Смартфоны"
        assert model.goods_subtype == "iPhone"


class TestCreateVariantPriceParsing:
    @pytest.mark.asyncio
    async def test_create_variant_invalid_price(self):
        """Non-numeric price falls back to None."""
        model = _make_model(id=1)
        added_objects = []

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=model)
        mock_db.commit = AsyncMock()
        mock_db.flush = AsyncMock()

        def track_add(obj):
            added_objects.append(obj)
            if hasattr(obj, "id") and obj.id is None:
                obj.id = 60

        mock_db.add = track_add
        app = _make_app(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            follow_redirects=False,
        ) as client:
            resp = await client.post(
                "/models/1/create-variant",
                data={
                    "title": "Test Shoe",
                    "price": "abc",
                    "account_id": "1",
                },
            )

        assert resp.status_code == 303
        # The Product should have price=None due to invalid string
        product_objs = [o for o in added_objects if hasattr(o, "title")]
        assert len(product_objs) >= 1
        assert product_objs[0].price is None


# ── Tests for GET /models/{id}/history ──

class TestModelHistory:
    @pytest.mark.asyncio
    async def test_history_not_found(self):
        """No products with published_at returns empty list."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/models/1/history")

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["items"] == []

    @pytest.mark.asyncio
    async def test_history_with_products(self):
        """Products with published_at returned with stats."""
        from datetime import datetime

        acc = MagicMock()
        acc.name = "TestAcc"

        product = MagicMock()
        product.id = 10
        product.account = acc
        product.status = "active"
        product.published_at = datetime(2026, 4, 10, 12, 0, 0)

        # Query 1: products
        r1_scalars = MagicMock()
        r1_scalars.all.return_value = [product]
        r1 = MagicMock()
        r1.scalars.return_value = r1_scalars

        # Query 2: stats
        stat_row = MagicMock()
        stat_row.product_id = 10
        stat_row.views = 150
        stat_row.contacts = 5
        r2 = MagicMock()
        r2.all.return_value = [stat_row]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=[r1, r2])
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/models/1/history")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1
        item = data["items"][0]
        assert item["product_id"] == 10
        assert item["account_name"] == "TestAcc"
        assert item["views"] == 150
        assert item["contacts"] == 5
        assert item["published_at"] == "10.04.2026"
        assert item["days_active"] >= 0


# ── Tests for accounts-status with markers ──

class TestAccountsStatusMarkers:
    @pytest.mark.asyncio
    async def test_includes_marker_and_views(self):
        """accounts-status returns marker, views_total, views_today, published_at."""
        from datetime import datetime, timezone

        acc = MagicMock()
        acc.id = 1
        acc.name = "TestAcc"
        acc.avito_sync_minute = None

        product = MagicMock()
        product.id = 10
        product.account_id = 1
        product.avito_id = 12345
        product.title = "Nike Air"
        product.size = "42"
        product.condition = "Новое с биркой"
        product.description = "Описание"
        product.use_custom_description = False
        product.price = 5000
        product.status = "active"
        product.scheduled_at = None
        product.published_at = datetime(2026, 4, 10, 12, 0, 0)
        product.variant_id = None
        product.images = []

        model = MagicMock()
        model.id = 1
        model.products = [product]
        model.photo_packs = []

        call_count = [0]
        def make_result(*args, **kwargs):
            call_count[0] += 1
            r = MagicMock()
            if call_count[0] == 1:  # model query
                r.scalar_one_or_none.return_value = model
            elif call_count[0] == 2:  # accounts
                r.scalars.return_value.all.return_value = [acc]
            else:  # stats queries + pack usage
                r.all.return_value = []
                r.scalars.return_value.all.return_value = []
            return r

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=make_result)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/models/1/accounts-status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert len(data["items"]) == 1
        item = data["items"][0]
        assert "marker" in item
        assert "views_total" in item
        assert "views_today" in item
        assert "published_at" in item
        assert item["published_at"] == "10.04.2026"
        assert "has_dead" in data


# ── Tests for unlinked-products and link-products ──

class TestUnlinkedProducts:
    @pytest.mark.asyncio
    async def test_returns_only_unlinked(self):
        """Only products with model_id=NULL are returned."""
        p1 = _make_product(id=1, model_id=None, status="imported", title="Unlinked Shoe")
        p1.account = _make_account(id=1, name="Shop1")

        # Products query
        r1_scalars = MagicMock()
        r1_scalars.all.return_value = [p1]
        r1 = MagicMock()
        r1.scalars.return_value = r1_scalars

        # Stats query (empty)
        r2 = MagicMock()
        r2.all.return_value = []

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=[r1, r2])
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/models/1/unlinked-products?q=shoe")

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert len(data["items"]) == 1
        assert data["items"][0]["title"] == "Unlinked Shoe"

    @pytest.mark.asyncio
    async def test_multiword_search(self):
        """Multi-word query applies AND logic — each word must match."""
        # The endpoint builds ILIKE filters per word. We test that the
        # endpoint is called successfully; actual SQL filtering is DB-level.
        r1_scalars = MagicMock()
        r1_scalars.all.return_value = []
        r1 = MagicMock()
        r1.scalars.return_value = r1_scalars

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=r1)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/models/1/unlinked-products?q=trainer+42")

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        # Verify execute was called (the multi-word WHERE clauses were built)
        assert mock_db.execute.called


class TestLinkProducts:
    @pytest.mark.asyncio
    async def test_links_unlinked_products(self):
        """Sets model_id on products where model_id IS NULL."""
        p1 = MagicMock()
        p1.id = 10
        p1.model_id = None
        p2 = MagicMock()
        p2.id = 20
        p2.model_id = None

        model = MagicMock()
        model.id = 5

        r_scalars = MagicMock()
        r_scalars.all.return_value = [p1, p2]
        r = MagicMock()
        r.scalars.return_value = r_scalars

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=model)
        mock_db.execute = AsyncMock(return_value=r)
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/models/5/link-products", json={"product_ids": [10, 20]})

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["linked"] == 2
        assert p1.model_id == 5
        assert p2.model_id == 5

    @pytest.mark.asyncio
    async def test_skips_already_linked(self):
        """Products with model_id already set are not returned by the query."""
        # The WHERE clause filters model_id IS NULL, so already-linked products
        # are simply not in the result set → linked count is 0.
        model = MagicMock()
        model.id = 5

        r_scalars = MagicMock()
        r_scalars.all.return_value = []  # no unlinked products matched
        r = MagicMock()
        r.scalars.return_value = r_scalars

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=model)
        mock_db.execute = AsyncMock(return_value=r)
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/models/5/link-products", json={"product_ids": [99]})

        assert resp.status_code == 200
        assert resp.json()["linked"] == 0


# ── GET /models/{id}/analytics ─────────────────────────────────────

class TestModelAnalytics:
    @pytest.mark.asyncio
    async def test_model_not_found(self):
        """Returns 404 when model doesn't exist."""
        mock_db = _empty_db()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/models/999/analytics")

        assert resp.status_code == 404
        assert resp.json()["ok"] is False

    @pytest.mark.asyncio
    async def test_no_active_products(self):
        """Returns empty items and 'no active' recommendation when model has no active products."""
        model = _make_model(id=5)
        # DB returns model via get, then empty product list via execute
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=model)
        mock_db.execute = AsyncMock(return_value=mock_result)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/models/5/analytics")

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["items"] == []
        assert data["recommendations"]["recommendation"] == "Нет активных объявлений по этой модели"
        assert data["recommendations"]["dead_count"] == 0
        assert data["recommendations"]["weak_count"] == 0
        assert data["recommendations"]["live_count"] == 0
