"""Tests for models routes (unit tests with mock DB)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from httpx import AsyncClient, ASGITransport

from app.db import get_db
from app.models.product import Product
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

    @pytest.mark.asyncio
    async def test_list_uses_original_url_for_yandex_pack(self):
        """Model list uses original pack image URL, not _thumb variant."""
        acc = _make_account(id=1, name="Zulla")
        yd_img = _make_image(url="/media/photo_packs/13/0_1.jpg", sort_order=0)
        pack = _make_photo_pack(id=13, name="YD Pack", images=[yd_img])
        product = _make_product(id=10, account_id=1, model_id=1)
        model = _make_model(id=1, products=[product], photo_packs=[pack])

        call_count = 0

        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalars.return_value.unique.return_value.all.return_value = [model]
            else:
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
            first_image = ctx["matrix"][0]["first_image"]
            assert first_image == "/media/photo_packs/13/0_1.jpg"
            assert "_thumb" not in first_image


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

    @pytest.mark.asyncio
    async def test_create_with_full_taxonomy(self):
        """Create model with all taxonomy fields returns JSON with id."""
        mock_db = AsyncMock()
        mock_db.commit = AsyncMock()

        created_model = None
        def mock_add(obj):
            nonlocal created_model
            obj.id = 50
            created_model = obj

        mock_db.add = mock_add
        app = _make_app(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/models",
                data={
                    "name": "Air Max 90",
                    "brand": "Nike",
                    "category": "Одежда, обувь, аксессуары",
                    "goods_type": "Мужская обувь",
                    "subcategory": "Кроссовки и кеды",
                    "goods_subtype": "Кроссовки",
                    "description": "Classic sneaker",
                },
                headers={"accept": "application/json"},
            )

        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert created_model.category == "Одежда, обувь, аксессуары"
        assert created_model.goods_subtype == "Кроссовки"

    @pytest.mark.asyncio
    async def test_create_no_subtype_when_not_required(self):
        """Subcategory without subtypes: goods_subtype not required."""
        mock_db = AsyncMock()
        mock_db.commit = AsyncMock()

        def mock_add(obj):
            obj.id = 51

        mock_db.add = mock_add
        app = _make_app(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/models",
                data={
                    "name": "Ray-Ban",
                    "brand": "Ray-Ban",
                    "category": "Одежда, обувь, аксессуары",
                    "goods_type": "Аксессуары",
                    "subcategory": "Очки",
                    "goods_subtype": "",
                },
                headers={"accept": "application/json"},
            )

        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    @pytest.mark.asyncio
    async def test_create_missing_subtype_when_required(self):
        """Subcategory requiring subtype: 400 if goods_subtype empty."""
        mock_db = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/models",
                data={
                    "name": "Air Max 90",
                    "brand": "Nike",
                    "category": "Одежда, обувь, аксессуары",
                    "goods_type": "Мужская обувь",
                    "subcategory": "Кроссовки и кеды",
                    "goods_subtype": "",
                },
                headers={"accept": "application/json"},
            )

        assert resp.status_code == 400
        assert "подтип" in resp.json()["error"].lower()


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
                # Accounts query
                result.scalars.return_value.all.return_value = [_make_account()]
            else:
                # get_catalog, packs_with_yd, description_templates queries
                result.scalar_one_or_none.return_value = None
                result.scalars.return_value.all.return_value = []
                result.all.return_value = []
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

    @pytest.mark.asyncio
    async def test_detail_includes_model_is_complete(self):
        """GET /models/{id} context includes model_is_complete and missing_fields."""
        model = _make_model(id=9, brand="Nike", description=None)
        model.category = None  # incomplete
        model.goods_type = "Мужская обувь"
        model.subcategory = None
        model.goods_subtype = "Кроссовки"

        call_count = 0

        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = model
            elif call_count == 2:
                result.scalars.return_value.all.return_value = [_make_account()]
            else:
                result.scalar_one_or_none.return_value = None
                result.scalars.return_value.all.return_value = []
                result.all.return_value = []
            return result

        mock_db = AsyncMock()
        mock_db.execute = mock_execute
        app = _make_app(mock_db)

        with patch("app.routes.models.templates") as mock_templates:
            mock_templates.TemplateResponse.return_value = HTMLResponse("<html></html>")
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/models/9")

            assert resp.status_code == 200
            ctx = mock_templates.TemplateResponse.call_args[0][1]
            assert ctx["model_is_complete"] is False
            assert "Категория" in ctx["missing_fields"]
            assert "Вид одежды/обуви" in ctx["missing_fields"]
            assert "Бренд" not in ctx["missing_fields"]  # brand is set

    @pytest.mark.asyncio
    async def test_detail_includes_description_templates(self):
        """GET /models/{id} context includes description_templates list."""
        model = _make_model(id=7, products=[], photo_packs=[])

        mock_tpl = MagicMock()
        mock_tpl.id = 10
        mock_tpl.name = "Кроссовки стандарт"

        call_count = 0

        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = model
            elif call_count == 2:
                result.scalars.return_value.all.return_value = [_make_account()]
            else:
                result.scalar_one_or_none.return_value = None
                result.scalars.return_value.all.return_value = [mock_tpl]
                result.all.return_value = []
            return result

        mock_db = AsyncMock()
        mock_db.execute = mock_execute
        app = _make_app(mock_db)

        with patch("app.routes.models.templates") as mock_templates:
            mock_templates.TemplateResponse.return_value = HTMLResponse("<html></html>")
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/models/7")

            assert resp.status_code == 200
            ctx = mock_templates.TemplateResponse.call_args[0][1]
            assert "description_templates" in ctx

    @pytest.mark.asyncio
    async def test_detail_photo_packs_in_context(self):
        """Model detail passes photo_packs with name and images to template."""
        img = _make_image(url="/media/photo_packs/1/photo.jpg", sort_order=0)
        pack = _make_photo_pack(id=1, name="Main Pack", images=[img])
        model = _make_model(id=3, products=[], photo_packs=[pack])

        call_count = 0

        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = model
            elif call_count == 2:
                result.scalars.return_value.all.return_value = [_make_account()]
            else:
                result.scalar_one_or_none.return_value = None
                result.scalars.return_value.all.return_value = []
                result.all.return_value = []
            return result

        mock_db = AsyncMock()
        mock_db.execute = mock_execute
        app = _make_app(mock_db)

        with patch("app.routes.models.templates") as mock_templates:
            mock_templates.TemplateResponse.return_value = HTMLResponse("<html></html>")
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/models/3")

            assert resp.status_code == 200
            ctx = mock_templates.TemplateResponse.call_args[0][1]
            packs = ctx["model"].photo_packs
            assert len(packs) == 1
            assert packs[0].name == "Main Pack"
            assert len(packs[0].images) == 1


# ── account_groups / recommendations in model_detail ─────────────────

class TestAccountGroups:
    """Tests for account_groups and recommendations computed in model_detail."""

    def _mock_execute_for_detail(self, model, accounts, stats_rows=None):
        """Build a mock_execute that handles all model_detail queries.

        Query order in model_detail (no photo_packs):
        1: Model, 2: Accounts, 3: get_catalog (returns None → fallback),
        4: description_templates, then 5-8: _compute_product_stats
        """
        call_count = 0

        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = model
            elif call_count == 2:
                result.scalars.return_value.all.return_value = accounts
            else:
                # get_catalog (scalar_one_or_none=None → fallback),
                # description_templates, _compute_product_stats queries
                result.scalar_one_or_none.return_value = None
                result.scalars.return_value.all.return_value = []
                result.all.return_value = []
            return result

        return mock_execute

    @pytest.mark.asyncio
    async def test_all_accounts_different_states(self):
        """4 accounts with dead, empty, weak, live → correct state_labels and sort order."""
        acc1 = _make_account(id=1, name="Parker")
        acc2 = _make_account(id=2, name="Рыбка")
        acc3 = _make_account(id=3, name="Zulla")
        acc4 = _make_account(id=4, name="Crosstherapy")

        # Products: acc1=dead, acc2=none, acc3=weak, acc4=live
        p1 = _make_product(id=10, account_id=1, avito_id=100, status="active")
        p3 = _make_product(id=30, account_id=3, avito_id=300, status="active")
        p4 = _make_product(id=40, account_id=4, avito_id=400, status="active")

        model = _make_model(id=5, products=[p1, p3, p4])

        call_count = 0

        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = model
            elif call_count == 2:
                result.scalars.return_value.all.return_value = [acc1, acc2, acc3, acc4]
            elif call_count == 5:
                # window query: pid 10 → dead (5 views), pid 30 → weak (25), pid 40 → live (50)
                r10 = MagicMock(product_id=10, max_views=105, min_views=100, cnt=3)
                r30 = MagicMock(product_id=30, max_views=125, min_views=100, cnt=3)
                r40 = MagicMock(product_id=40, max_views=150, min_views=100, cnt=3)
                result.all.return_value = [r10, r30, r40]
            elif call_count == 6:
                # baseline query
                b10 = MagicMock(product_id=10, bv=100)
                b30 = MagicMock(product_id=30, bv=100)
                b40 = MagicMock(product_id=40, bv=100)
                result.all.return_value = [b10, b30, b40]
            else:
                # get_catalog, desc_templates, today/yesterday
                result.scalar_one_or_none.return_value = None
                result.scalars.return_value.all.return_value = []
                result.all.return_value = []
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
            groups = ctx["account_groups"]

            assert len(groups) == 4
            states = [g["state"] for g in groups]
            # Sort order: dead(1), empty(2), weak(3), live(6)
            assert states == ["dead", "empty", "weak", "live"]
            labels = [g["state_label"] for g in groups]
            assert labels == ["мёртвое", "нет объявлений", "слабое", "живое"]

    @pytest.mark.asyncio
    async def test_empty_account_state(self):
        """Account with no products → state='empty'."""
        acc = _make_account(id=1, name="TestAcc")
        model = _make_model(id=1, products=[])

        mock_db = AsyncMock()
        mock_db.execute = self._mock_execute_for_detail(model, [acc])
        app = _make_app(mock_db)

        with patch("app.routes.models.templates") as mock_templates:
            mock_templates.TemplateResponse.return_value = HTMLResponse("<html></html>")
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                await client.get("/models/1")

            ctx = mock_templates.TemplateResponse.call_args[0][1]
            groups = ctx["account_groups"]
            assert len(groups) == 1
            assert groups[0]["state"] == "empty"
            assert groups[0]["product_count"] == 0

    @pytest.mark.asyncio
    async def test_two_dead_one_draft_state_is_dead(self):
        """2 dead products + 1 draft on same account → state='dead'."""
        acc = _make_account(id=1, name="Parker")
        p1 = _make_product(id=10, account_id=1, avito_id=100, status="active")
        p2 = _make_product(id=11, account_id=1, avito_id=101, status="active")
        p3 = _make_product(id=12, account_id=1, status="draft")
        model = _make_model(id=1, products=[p1, p2, p3])

        call_count = 0

        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = model
            elif call_count == 2:
                result.scalars.return_value.all.return_value = [acc]
            elif call_count == 5:
                # window: both products have < 20 views_5d → dead
                r1 = MagicMock(product_id=10, max_views=110, min_views=100, cnt=3)
                r2 = MagicMock(product_id=11, max_views=108, min_views=100, cnt=3)
                result.all.return_value = [r1, r2]
            elif call_count == 6:
                # baseline
                b1 = MagicMock(product_id=10, bv=100)
                b2 = MagicMock(product_id=11, bv=100)
                result.all.return_value = [b1, b2]
            else:
                # get_catalog, desc_templates, today/yesterday
                result.scalar_one_or_none.return_value = None
                result.scalars.return_value.all.return_value = []
                result.all.return_value = []
            return result

        mock_db = AsyncMock()
        mock_db.execute = mock_execute
        app = _make_app(mock_db)

        with patch("app.routes.models.templates") as mock_templates:
            mock_templates.TemplateResponse.return_value = HTMLResponse("<html></html>")
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                await client.get("/models/1")

            ctx = mock_templates.TemplateResponse.call_args[0][1]
            groups = ctx["account_groups"]
            assert groups[0]["state"] == "dead"
            # Check individual markers
            markers = [p.marker for p in groups[0]["products"] if p.avito_id]
            assert markers.count("dead") == 2

    @pytest.mark.asyncio
    async def test_recommendations_missing_listing(self):
        """Empty account generates missing_listing recommendation."""
        acc1 = _make_account(id=1, name="Parker")
        acc2 = _make_account(id=2, name="Рыбка")
        p1 = _make_product(id=10, account_id=1, avito_id=100, status="active")
        model = _make_model(id=7, products=[p1])

        call_count = 0

        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = model
            elif call_count == 2:
                result.scalars.return_value.all.return_value = [acc1, acc2]
            elif call_count == 5:
                # window: pid 10 → live (50 views)
                r = MagicMock(product_id=10, max_views=150, min_views=100, cnt=3)
                result.all.return_value = [r]
            elif call_count == 6:
                b = MagicMock(product_id=10, bv=100)
                result.all.return_value = [b]
            else:
                # get_catalog, desc_templates, today/yesterday
                result.scalar_one_or_none.return_value = None
                result.scalars.return_value.all.return_value = []
                result.all.return_value = []
            return result

        mock_db = AsyncMock()
        mock_db.execute = mock_execute
        app = _make_app(mock_db)

        with patch("app.routes.models.templates") as mock_templates:
            mock_templates.TemplateResponse.return_value = HTMLResponse("<html></html>")
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                await client.get("/models/7")

            ctx = mock_templates.TemplateResponse.call_args[0][1]
            recs = ctx["recommendations"]
            missing = [r for r in recs if r["kind"] == "missing_listing"]
            assert len(missing) == 1
            assert missing[0]["account_id"] == 2
            assert "Рыбка" in missing[0]["title"]

    @pytest.mark.asyncio
    async def test_recommendations_revive_dead(self):
        """Dead accounts generate a single revive_dead recommendation with account names."""
        acc1 = _make_account(id=1, name="Parker")
        acc2 = _make_account(id=2, name="Zulla")
        p1 = _make_product(id=10, account_id=1, avito_id=100, status="active")
        p2 = _make_product(id=20, account_id=2, avito_id=200, status="active")
        model = _make_model(id=3, products=[p1, p2])

        call_count = 0

        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = model
            elif call_count == 2:
                result.scalars.return_value.all.return_value = [acc1, acc2]
            elif call_count == 5:
                # window: both dead (< 20 views)
                r1 = MagicMock(product_id=10, max_views=105, min_views=100, cnt=3)
                r2 = MagicMock(product_id=20, max_views=108, min_views=100, cnt=3)
                result.all.return_value = [r1, r2]
            elif call_count == 6:
                b1 = MagicMock(product_id=10, bv=100)
                b2 = MagicMock(product_id=20, bv=100)
                result.all.return_value = [b1, b2]
            else:
                # get_catalog, desc_templates, today/yesterday
                result.scalar_one_or_none.return_value = None
                result.scalars.return_value.all.return_value = []
                result.all.return_value = []
            return result

        mock_db = AsyncMock()
        mock_db.execute = mock_execute
        app = _make_app(mock_db)

        with patch("app.routes.models.templates") as mock_templates:
            mock_templates.TemplateResponse.return_value = HTMLResponse("<html></html>")
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                await client.get("/models/3")

            ctx = mock_templates.TemplateResponse.call_args[0][1]
            recs = ctx["recommendations"]
            revive = [r for r in recs if r["kind"] == "revive_dead"]
            assert len(revive) == 1
            assert set(revive[0]["account_ids"]) == {1, 2}
            assert "Parker" in revive[0]["title"]
            assert "Zulla" in revive[0]["title"]
            assert "2 объявлений" in revive[0]["description"]

    @pytest.mark.asyncio
    async def test_product_stats_fields_attached(self):
        """Products in account_groups have .marker, .views_5d, .delta_day."""
        acc = _make_account(id=1, name="Parker")
        p = _make_product(id=10, account_id=1, avito_id=100, status="active")
        model = _make_model(id=1, products=[p])

        call_count = 0

        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = model
            elif call_count == 2:
                result.scalars.return_value.all.return_value = [acc]
            elif call_count == 5:
                # window: 35 views → alive
                r = MagicMock(product_id=10, max_views=135, min_views=100, cnt=3)
                result.all.return_value = [r]
            elif call_count == 6:
                b = MagicMock(product_id=10, bv=100)
                result.all.return_value = [b]
            elif call_count == 7:
                # today
                t = MagicMock(product_id=10, v=140)
                result.all.return_value = [t]
            elif call_count == 8:
                # yesterday
                y = MagicMock(product_id=10, v=130)
                result.all.return_value = [y]
            else:
                # get_catalog, desc_templates
                result.scalar_one_or_none.return_value = None
                result.scalars.return_value.all.return_value = []
                result.all.return_value = []
            return result

        mock_db = AsyncMock()
        mock_db.execute = mock_execute
        app = _make_app(mock_db)

        with patch("app.routes.models.templates") as mock_templates:
            mock_templates.TemplateResponse.return_value = HTMLResponse("<html></html>")
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                await client.get("/models/1")

            ctx = mock_templates.TemplateResponse.call_args[0][1]
            product = ctx["account_groups"][0]["products"][0]
            assert product.marker == "alive"
            assert product.views_5d == 35
            assert product.delta_day == 10

    @pytest.mark.asyncio
    async def test_scheduled_state(self):
        """All products in draft/scheduled → state='scheduled'."""
        acc = _make_account(id=1, name="Parker")
        p = _make_product(id=10, account_id=1, status="scheduled")
        model = _make_model(id=1, products=[p])

        mock_db = AsyncMock()
        mock_db.execute = self._mock_execute_for_detail(model, [acc])
        app = _make_app(mock_db)

        with patch("app.routes.models.templates") as mock_templates:
            mock_templates.TemplateResponse.return_value = HTMLResponse("<html></html>")
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                await client.get("/models/1")

            ctx = mock_templates.TemplateResponse.call_args[0][1]
            groups = ctx["account_groups"]
            assert groups[0]["state"] == "scheduled"
            assert groups[0]["state_label"] == "в расписании"


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


# ── POST /models/{id}/products (create_model_product) ─────────────


class TestCreateModelProduct:
    @pytest.mark.asyncio
    async def test_copies_description_from_model(self):
        """Model with description → product gets description + use_custom_description=True."""
        model = _make_model(id=10, description="Model description text")
        created_product = None

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=model)
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()

        original_add = mock_db.add

        def capture_add(obj):
            nonlocal created_product
            if isinstance(obj, Product):
                created_product = obj
            return original_add(obj)

        mock_db.add = MagicMock(side_effect=capture_add)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/models/10/products", json={"account_id": 1})

        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert created_product is not None
        assert created_product.description == "Model description text"
        assert created_product.use_custom_description is True

    @pytest.mark.asyncio
    async def test_no_description_model_leaves_null(self):
        """Model without description → product.description=None, use_custom_description=False."""
        model = _make_model(id=11, description=None)
        created_product = None

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=model)
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()

        def capture_add(obj):
            nonlocal created_product
            if isinstance(obj, Product):
                created_product = obj

        mock_db.add = MagicMock(side_effect=capture_add)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/models/11/products", json={"account_id": 1})

        assert resp.status_code == 200
        assert created_product is not None
        assert created_product.description is None
        assert created_product.use_custom_description is False

    @pytest.mark.asyncio
    async def test_accepts_description_template_id(self):
        """POST with description_template_id → saved on product."""
        model = _make_model(id=12)
        created_product = None

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=model)
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()

        def capture_add(obj):
            nonlocal created_product
            if isinstance(obj, Product):
                created_product = obj

        mock_db.add = MagicMock(side_effect=capture_add)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/models/12/products", json={
                "account_id": 1,
                "description_template_id": 5,
            })

        assert resp.status_code == 200
        assert created_product is not None
        assert created_product.description_template_id == 5

    @pytest.mark.asyncio
    async def test_no_description_template_id_is_null(self):
        """POST without description_template_id → product.description_template_id=None."""
        model = _make_model(id=13)
        created_product = None

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=model)
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()

        def capture_add(obj):
            nonlocal created_product
            if isinstance(obj, Product):
                created_product = obj

        mock_db.add = MagicMock(side_effect=capture_add)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/models/13/products", json={"account_id": 1})

        assert resp.status_code == 200
        assert created_product is not None
        assert created_product.description_template_id is None


# ── Integration tests: copy_variant, create_all_listings, schedule_matrix ──


class TestCopyVariantPreservesTemplate:
    @pytest.mark.asyncio
    async def test_copy_variant_preserves_template_link(self, isolated_db):
        """copy_variant must copy use_custom_description and description_template_id from source."""
        import uuid
        from sqlalchemy import text, select as sa_select
        from app.models.account import Account
        from app.models.model import Model as ModelORM
        from app.models.description_template import DescriptionTemplate
        from app.models.product import Product as ProductORM
        from app.models.product_image import ProductImage

        await isolated_db.execute(text(
            "SELECT setval('accounts_id_seq', GREATEST(nextval('accounts_id_seq'), "
            "(SELECT COALESCE(MAX(id), 0) FROM accounts)))"
        ))
        token = uuid.uuid4().hex[:8]
        acc1 = Account(name=f"CopySrc-{token}", client_id=f"cs-{token}",
                       client_secret="s", feed_token=f"fs-{token}")
        acc2 = Account(name=f"CopyDst-{token}", client_id=f"cd-{token}",
                       client_secret="s", feed_token=f"fd-{token}")
        isolated_db.add(acc1)
        isolated_db.add(acc2)
        await isolated_db.flush()

        model = ModelORM(name=f"CopyModel-{token}", brand="Nike")
        isolated_db.add(model)
        await isolated_db.flush()

        tpl = DescriptionTemplate(name=f"CopyTpl-{token}", body="tpl body")
        isolated_db.add(tpl)
        await isolated_db.flush()

        source = ProductORM(
            title="Source Variant", description="SRC DESC", price=5000,
            status="active", account_id=acc1.id, model_id=model.id,
            category="Одежда", goods_type="Мужская обувь",
            subcategory="Кроссовки", goods_subtype="Кроссовки",
            brand="Nike", condition="Новое с биркой",
            use_custom_description=True,
            description_template_id=tpl.id,
        )
        isolated_db.add(source)
        await isolated_db.flush()
        isolated_db.add(ProductImage(product_id=source.id, url="/media/cv.jpg",
                            filename="cv.jpg", sort_order=0, is_main=True))
        await isolated_db.flush()

        from fastapi import FastAPI
        from app.db import get_db
        from app.routes.models import router as models_router

        app = FastAPI()
        app.include_router(models_router)

        async def override_db():
            yield isolated_db

        app.dependency_overrides[get_db] = override_db

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(f"/models/{model.id}/copy-variant", json={
                "product_id": source.id,
                "account_id": acc2.id,
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True

        copy = await isolated_db.get(ProductORM, data["new_product_id"])
        assert copy.description_template_id == tpl.id
        assert copy.use_custom_description is True
        assert copy.description == "SRC DESC"
