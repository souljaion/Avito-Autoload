"""Tests for ad title generation and editable title in matrix.

- _default_ad_title: no brand duplication
- create_model_product: accepts explicit title override
- create_model_product: auto-generates clean title when no override
"""

import uuid

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text

from app.models.account import Account
from app.models.model import Model as ModelORM
from app.models.product import Product as ProductORM
from app.routes.models import _default_ad_title


class TestDefaultAdTitle:
    """Unit tests for _default_ad_title helper."""

    def test_brand_already_in_name(self):
        """model.name starts with brand → no duplication."""
        m = type("M", (), {"name": "Adidas CP бежевые", "brand": "Adidas"})()
        assert _default_ad_title(m) == "Adidas CP бежевые"

    def test_brand_not_in_name(self):
        """model.name doesn't contain brand → prepend."""
        m = type("M", (), {"name": "CP бежевые", "brand": "Adidas"})()
        assert _default_ad_title(m) == "Adidas CP бежевые"

    def test_brand_exact_match(self):
        """model.name == brand → no duplication."""
        m = type("M", (), {"name": "Adidas", "brand": "Adidas"})()
        assert _default_ad_title(m) == "Adidas"

    def test_no_brand(self):
        """No brand → just name."""
        m = type("M", (), {"name": "Some Shoe", "brand": ""})()
        assert _default_ad_title(m) == "Some Shoe"

    def test_no_name(self):
        """No name → just brand."""
        m = type("M", (), {"name": "", "brand": "Nike"})()
        assert _default_ad_title(m) == "Nike"

    def test_case_insensitive(self):
        """Brand match is case-insensitive."""
        m = type("M", (), {"name": "adidas Trainer", "brand": "Adidas"})()
        assert _default_ad_title(m) == "adidas Trainer"


def _make_app(isolated_db):
    from fastapi import FastAPI
    from app.db import get_db
    from app.routes.models import router as models_router
    from app.routes.products import router as products_router

    app = FastAPI()
    app.include_router(models_router)
    app.include_router(products_router)

    async def override_db():
        yield isolated_db

    app.dependency_overrides[get_db] = override_db
    return app


async def _seed(db):
    await db.execute(text(
        "SELECT setval('accounts_id_seq', GREATEST(nextval('accounts_id_seq'), "
        "(SELECT COALESCE(MAX(id), 0) FROM accounts)))"
    ))
    token = uuid.uuid4().hex[:8]
    acc = Account(name=f"Title-{token}", client_id=f"t-{token}",
                  client_secret="s", feed_token=f"tft-{token}")
    db.add(acc)
    await db.flush()

    model = ModelORM(
        name=f"Adidas CP бежевые {token}", brand="Adidas",
        category="Одежда, обувь, аксессуары", goods_type="Мужская обувь",
        subcategory="Кроссовки и кеды", goods_subtype="Кроссовки",
    )
    db.add(model)
    await db.flush()
    return acc, model


class TestCreateModelProductTitle:

    @pytest.mark.asyncio
    async def test_explicit_title_override(self, isolated_db):
        """POST with title='Custom name' → product has that title."""
        acc, model = await _seed(isolated_db)
        app = _make_app(isolated_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(f"/models/{model.id}/products", json={
                "account_id": acc.id,
                "title": "My Custom Ad Name",
            })

        data = resp.json()
        assert data["ok"] is True
        product = await isolated_db.get(ProductORM, data["product_id"])
        assert product.title == "My Custom Ad Name"

    @pytest.mark.asyncio
    async def test_auto_title_no_brand_duplication(self, isolated_db):
        """POST without title → product gets clean auto-generated title (no double brand)."""
        acc, model = await _seed(isolated_db)
        app = _make_app(isolated_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(f"/models/{model.id}/products", json={
                "account_id": acc.id,
            })

        data = resp.json()
        assert data["ok"] is True
        product = await isolated_db.get(ProductORM, data["product_id"])
        # model.name already starts with "Adidas" → should NOT be "Adidas Adidas CP..."
        assert not product.title.startswith("Adidas Adidas")
        assert product.title == model.name

    @pytest.mark.asyncio
    async def test_patch_title(self, isolated_db):
        """PATCH /products/{id} with title → title updated."""
        acc, model = await _seed(isolated_db)
        app = _make_app(isolated_db)

        # Create product first
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(f"/models/{model.id}/products", json={
                "account_id": acc.id,
            })
            pid = resp.json()["product_id"]

            # Now patch the title
            resp2 = await c.patch(f"/products/{pid}", json={"title": "Updated Title"})

        assert resp2.status_code == 200
        assert resp2.json()["ok"] is True
        product = await isolated_db.get(ProductORM, pid)
        assert product.title == "Updated Title"
