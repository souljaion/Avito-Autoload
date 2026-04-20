"""Tests for /products/{id}/edit?inline=1 endpoint."""

import uuid

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text

from app.models.account import Account
from app.models.model import Model as ModelORM
from app.models.product import Product as ProductORM


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
