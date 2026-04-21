"""Tests for /products/{id}/edit?inline=1 endpoint."""

import uuid

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text

from app.models.account import Account
from app.models.model import Model as ModelORM
from app.models.product import Product as ProductORM
from app.models.product_image import ProductImage


def _make_app(isolated_db):
    from fastapi import FastAPI
    from app.db import get_db
    from app.routes.products import router as products_router

    app = FastAPI()
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
    acc = Account(name=f"Inline-{token}", client_id=f"il-{token}",
                  client_secret="s", feed_token=f"ilft-{token}")
    db.add(acc)
    await db.flush()

    product = ProductORM(
        title="Test Product Inline",
        brand="TestBrand",
        price=5000,
        status="draft",
        account_id=acc.id,
        category="Одежда, обувь, аксессуары",
        goods_type="Мужская обувь",
        subcategory="Кроссовки и кеды",
        condition="Новое с биркой",
    )
    db.add(product)
    await db.flush()
    return acc, product


class TestInlineEdit:

    @pytest.mark.asyncio
    async def test_inline_returns_form_without_nav(self, isolated_db):
        """GET /products/{id}/edit?inline=1 returns form HTML without sidebar/nav."""
        acc, product = await _seed(isolated_db)
        app = _make_app(isolated_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get(f"/products/{product.id}/edit?inline=1")

        assert resp.status_code == 200
        html = resp.text
        # Has form fields
        assert 'name="title"' in html
        assert 'name="price"' in html
        assert 'name="description"' in html
        assert 'id="inline-edit-form"' in html
        # Has hidden inline field
        assert 'name="inline" value="1"' in html
        # Does NOT have sidebar/nav from base.html
        assert "sidebar" not in html
        assert "sidebar-nav" not in html

    @pytest.mark.asyncio
    async def test_regular_edit_has_nav(self, isolated_db):
        """GET /products/{id}/edit (no inline) returns full page with nav."""
        acc, product = await _seed(isolated_db)
        app = _make_app(isolated_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get(f"/products/{product.id}/edit")

        assert resp.status_code == 200
        html = resp.text
        assert 'name="title"' in html
        # Has base.html layout elements
        assert "sidebar" in html

    @pytest.mark.asyncio
    async def test_inline_form_action_same(self, isolated_db):
        """Both inline and regular forms POST to the same action URL."""
        acc, product = await _seed(isolated_db)
        app = _make_app(isolated_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp_inline = await c.get(f"/products/{product.id}/edit?inline=1")
            resp_full = await c.get(f"/products/{product.id}/edit")

        # Both have method="post" (action defaults to current URL)
        assert 'method="post"' in resp_inline.text
        assert 'method="post"' in resp_full.text

    @pytest.mark.asyncio
    async def test_inline_edit_nonexistent_404(self, isolated_db):
        """GET /products/99999/edit?inline=1 returns 404."""
        app = _make_app(isolated_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/products/99999/edit?inline=1")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_inline_post_uses_origin_not_wildcard(self, isolated_db):
        """POST with inline=1 returns postMessage with window.location.origin, not '*'."""
        acc, product = await _seed(isolated_db)
        app = _make_app(isolated_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                f"/products/{product.id}/edit",
                data={
                    "title": product.title,
                    "price": str(product.price),
                    "brand": product.brand or "",
                    "category": product.category or "",
                    "goods_type": product.goods_type or "",
                    "subcategory": product.subcategory or "",
                    "goods_subtype": "",
                    "size": "",
                    "color": "",
                    "material": "",
                    "condition": product.condition or "",
                    "description": "test desc",
                    "status": "draft",
                    "scheduled_at": "",
                    "scheduled_account_id": "",
                    "model_id": "",
                    "inline": "1",
                },
                follow_redirects=False,
            )

        assert resp.status_code == 200
        html = resp.text
        assert "window.location.origin" in html
        # Must NOT contain '"*"' as targetOrigin in postMessage
        assert 'postMessage(' in html
        assert '"*"' not in html

    @pytest.mark.asyncio
    async def test_save_only_does_not_change_status(self, isolated_db):
        """POST inline save updates fields but does NOT change status to scheduled."""
        acc, product = await _seed(isolated_db)
        app = _make_app(isolated_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                f"/products/{product.id}/edit",
                data={
                    "title": "Updated Title",
                    "price": "7777",
                    "brand": product.brand or "",
                    "category": product.category or "",
                    "goods_type": product.goods_type or "",
                    "subcategory": product.subcategory or "",
                    "goods_subtype": "",
                    "size": "",
                    "color": "",
                    "material": "",
                    "condition": product.condition or "",
                    "description": "updated desc",
                    "status": "draft",
                    "scheduled_at": "",
                    "scheduled_account_id": "",
                    "model_id": "",
                    "inline": "1",
                },
                follow_redirects=False,
            )

        assert resp.status_code == 200
        # product-saved postMessage returned
        assert "product-saved" in resp.text

        # Verify product was updated but status stays draft
        await isolated_db.refresh(product)
        assert product.title == "Updated Title"
        assert product.price == 7777
        assert product.status == "draft"
        assert product.scheduled_at is None

    @pytest.mark.asyncio
    async def test_save_and_publish_changes_status(self, isolated_db):
        """Bulk-publish after inline save sets status=scheduled and scheduled_at."""
        from app.routes.models import router as models_router

        acc, product = await _seed(isolated_db)

        # Create a model linked to the product
        model = ModelORM(name="Test Model", brand="TestBrand")
        isolated_db.add(model)
        await isolated_db.flush()
        product.model_id = model.id
        product.description = "Test description for publish"
        product.goods_subtype = "Кроссовки"
        await isolated_db.flush()
        # Add an image (required for feed readiness)
        img = ProductImage(product_id=product.id, url="https://example.com/test.jpg", filename="test.jpg")
        isolated_db.add(img)
        await isolated_db.flush()

        app = _make_app(isolated_db)
        app.include_router(models_router)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            # First: inline save
            resp = await c.post(
                f"/products/{product.id}/edit",
                data={
                    "title": product.title,
                    "price": str(product.price),
                    "brand": product.brand or "",
                    "category": product.category or "",
                    "goods_type": product.goods_type or "",
                    "subcategory": product.subcategory or "",
                    "goods_subtype": product.goods_subtype or "",
                    "size": "",
                    "color": "",
                    "material": "",
                    "condition": product.condition or "",
                    "description": product.description or "",
                    "status": "draft",
                    "account_id": str(acc.id),
                    "scheduled_at": "",
                    "scheduled_account_id": "",
                    "model_id": str(model.id),
                    "inline": "1",
                },
                follow_redirects=False,
            )
            assert resp.status_code == 200

            # Second: bulk-publish (what "Сохранить и опубликовать" does after save)
            resp2 = await c.post(
                f"/models/{model.id}/bulk-publish",
                json={"product_ids": [product.id]},
            )

        assert resp2.status_code == 200
        data = resp2.json()
        assert data["ok"] is True
        assert data["published"] == 1

        await isolated_db.refresh(product)
        assert product.status == "scheduled"
        assert product.scheduled_at is not None

    @pytest.mark.asyncio
    async def test_carousel_multi_select_sequential(self, isolated_db):
        """Simulates carousel: save-only product1, save+publish product2."""
        from app.routes.models import router as models_router

        acc, product1 = await _seed(isolated_db)

        # Create second product
        product2 = ProductORM(
            title="Product Two", brand="TestBrand", price=9000, status="draft",
            account_id=acc.id, category="Одежда, обувь, аксессуары",
            goods_type="Мужская обувь", subcategory="Кроссовки и кеды",
            goods_subtype="Кроссовки", condition="Новое с биркой",
            description="Desc for product 2",
        )
        isolated_db.add(product2)
        await isolated_db.flush()

        model = ModelORM(name="Carousel Model", brand="TestBrand")
        isolated_db.add(model)
        await isolated_db.flush()
        product1.model_id = model.id
        product1.description = "Desc for product 1"
        product1.goods_subtype = "Кроссовки"
        product2.model_id = model.id
        await isolated_db.flush()

        img1 = ProductImage(product_id=product1.id, url="https://example.com/1.jpg", filename="1.jpg")
        img2 = ProductImage(product_id=product2.id, url="https://example.com/2.jpg", filename="2.jpg")
        isolated_db.add_all([img1, img2])
        await isolated_db.flush()

        app = _make_app(isolated_db)
        app.include_router(models_router)

        _form = lambda p: {
            "title": p.title, "price": str(p.price), "brand": p.brand or "",
            "category": p.category or "", "goods_type": p.goods_type or "",
            "subcategory": p.subcategory or "", "goods_subtype": p.goods_subtype or "",
            "size": "", "color": "", "material": "", "condition": p.condition or "",
            "description": p.description or "", "status": "draft",
            "account_id": str(acc.id), "scheduled_at": "",
            "scheduled_account_id": "", "model_id": str(model.id), "inline": "1",
        }

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            # Carousel item 1: save-only
            resp1 = await c.post(f"/products/{product1.id}/edit", data=_form(product1), follow_redirects=False)
            assert resp1.status_code == 200
            assert "product-saved" in resp1.text

            # Carousel item 2: save + publish
            resp2 = await c.post(f"/products/{product2.id}/edit", data=_form(product2), follow_redirects=False)
            assert resp2.status_code == 200
            resp3 = await c.post(f"/models/{model.id}/bulk-publish", json={"product_ids": [product2.id]})
            assert resp3.status_code == 200
            assert resp3.json()["published"] == 1

        await isolated_db.refresh(product1)
        await isolated_db.refresh(product2)
        # Product 1: save-only → stays draft
        assert product1.status == "draft"
        assert product1.scheduled_at is None
        # Product 2: save+publish → scheduled
        assert product2.status == "scheduled"
        assert product2.scheduled_at is not None
