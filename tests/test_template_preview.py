"""Tests for template preview panel on /products/{id}/edit."""

import uuid

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text

from app.models.account import Account
from app.models.product import Product as ProductORM
from app.models.description_template import DescriptionTemplate


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


async def _seed(db, *, with_template=True):
    await db.execute(text(
        "SELECT setval('accounts_id_seq', GREATEST(nextval('accounts_id_seq'), "
        "(SELECT COALESCE(MAX(id), 0) FROM accounts)))"
    ))
    token = uuid.uuid4().hex[:8]
    acc = Account(name=f"TplPrev-{token}", client_id=f"tp-{token}",
                  client_secret="s", feed_token=f"tpft-{token}")
    db.add(acc)
    await db.flush()

    tpl = None
    tpl_id = None
    if with_template:
        tpl = DescriptionTemplate(name=f"TestTpl-{token}", body=f"Template body text {token}")
        db.add(tpl)
        await db.flush()
        tpl_id = tpl.id

    product = ProductORM(
        title="Test Preview Product",
        brand="TestBrand",
        price=5000,
        status="draft",
        account_id=acc.id,
        category="Одежда, обувь, аксессуары",
        goods_type="Мужская обувь",
        subcategory="Кроссовки и кеды",
        condition="Новое с биркой",
        description_template_id=tpl_id,
    )
    db.add(product)
    await db.flush()
    return acc, product, tpl


class TestTemplatePreview:

    @pytest.mark.asyncio
    async def test_edit_with_template_shows_panel(self, isolated_db):
        """Product with template → edit page shows details panel with template name and body."""
        acc, product, tpl = await _seed(isolated_db, with_template=True)
        app = _make_app(isolated_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get(f"/products/{product.id}/edit")

        assert resp.status_code == 200
        html = resp.text
        assert "<details" in html
        assert tpl.name in html
        assert tpl.body in html

    @pytest.mark.asyncio
    async def test_edit_without_template_no_panel(self, isolated_db):
        """Product without template → edit page does NOT show details panel."""
        acc, product, _ = await _seed(isolated_db, with_template=False)
        app = _make_app(isolated_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get(f"/products/{product.id}/edit")

        assert resp.status_code == 200
        html = resp.text
        assert '<details class="tpl-preview-panel"' not in html

    @pytest.mark.asyncio
    async def test_inline_with_template_shows_panel(self, isolated_db):
        """Product with template → inline edit also shows the panel."""
        acc, product, tpl = await _seed(isolated_db, with_template=True)
        app = _make_app(isolated_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get(f"/products/{product.id}/edit?inline=1")

        assert resp.status_code == 200
        html = resp.text
        assert "<details" in html
        assert tpl.name in html
        assert tpl.body in html
