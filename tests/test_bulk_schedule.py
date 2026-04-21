"""Tests for bulk schedule from /models/{id}/bulk-schedule endpoint.

Uses isolated_db because the endpoint calls db.commit().
"""

import uuid

import pytest
from base64 import b64encode
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text, select as sa_select

from app.models.account import Account
from app.models.model import Model as ModelORM
from app.models.product import Product as ProductORM
from app.models.listing import Listing


def _make_app(isolated_db):
    from fastapi import FastAPI
    from app.db import get_db
    from app.routes.models import router as models_router

    app = FastAPI()
    app.include_router(models_router)

    async def override_db():
        yield isolated_db

    app.dependency_overrides[get_db] = override_db
    return app


async def _seed(db, *, count=2):
    """Create account, model, and N draft products (no images, no description)."""
    await db.execute(text(
        "SELECT setval('accounts_id_seq', GREATEST(nextval('accounts_id_seq'), "
        "(SELECT COALESCE(MAX(id), 0) FROM accounts)))"
    ))
    token = uuid.uuid4().hex[:8]
    acc = Account(name=f"Sched-{token}", client_id=f"sch-{token}",
                  client_secret="s", feed_token=f"schft-{token}")
    db.add(acc)
    await db.flush()

    model = ModelORM(
        name=f"SchedModel-{token}", brand="TestBrand",
        category="Одежда, обувь, аксессуары", goods_type="Мужская обувь",
        subcategory="Кроссовки и кеды",
    )
    db.add(model)
    await db.flush()

    products = []
    for i in range(count):
        p = ProductORM(
            title=f"Draft {i}", status="draft",
            account_id=acc.id, model_id=model.id,
            category="Одежда, обувь, аксессуары",
        )
        db.add(p)
        await db.flush()
        db.add(Listing(product_id=p.id, account_id=acc.id, status="draft"))
        products.append(p)

    await db.flush()
    return acc, model, products


class TestBulkSchedule:
    """POST /models/{id}/bulk-schedule — move drafts to scheduled without time."""

    @pytest.mark.asyncio
    async def test_sets_status_scheduled_and_null_scheduled_at(self, isolated_db):
        """Drafts become scheduled with scheduled_at=NULL."""
        acc, model, products = await _seed(isolated_db)
        app = _make_app(isolated_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(f"/models/{model.id}/bulk-schedule", json={
                "product_ids": [p.id for p in products],
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert len(data["scheduled"]) == 2
        assert data["skipped"] == []

        for p in products:
            await isolated_db.refresh(p)
            assert p.status == "scheduled"
            assert p.scheduled_at is None

    @pytest.mark.asyncio
    async def test_syncs_listing_status(self, isolated_db):
        """Listings for scheduled products also become scheduled."""
        acc, model, products = await _seed(isolated_db)
        app = _make_app(isolated_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            await c.post(f"/models/{model.id}/bulk-schedule", json={
                "product_ids": [products[0].id],
            })

        result = await isolated_db.execute(
            sa_select(Listing).where(Listing.product_id == products[0].id)
        )
        listing = result.scalar_one()
        assert listing.status == "scheduled"
        assert listing.scheduled_at is None

    @pytest.mark.asyncio
    async def test_skips_non_draft(self, isolated_db):
        """Non-draft products are skipped."""
        acc, model, products = await _seed(isolated_db)
        products[1].status = "active"
        await isolated_db.flush()

        app = _make_app(isolated_db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(f"/models/{model.id}/bulk-schedule", json={
                "product_ids": [p.id for p in products],
            })

        data = resp.json()
        assert len(data["scheduled"]) == 1
        assert data["scheduled"][0] == products[0].id
        assert len(data["skipped"]) == 1
        assert data["skipped"][0]["id"] == products[1].id

    @pytest.mark.asyncio
    async def test_no_readiness_check(self, isolated_db):
        """Drafts without images/description are still scheduled (no readiness check)."""
        acc, model, products = await _seed(isolated_db)
        # products have no images, no description — would fail readiness check
        app = _make_app(isolated_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(f"/models/{model.id}/bulk-schedule", json={
                "product_ids": [products[0].id],
            })

        data = resp.json()
        assert data["ok"] is True
        assert len(data["scheduled"]) == 1

    @pytest.mark.asyncio
    async def test_scheduled_badge_in_template(self, isolated_db):
        """Scheduled product shows badge in model detail page."""
        from app.config import settings

        acc, model, products = await _seed(isolated_db, count=1)
        products[0].status = "scheduled"
        await isolated_db.flush()

        from app.main import app as real_app
        from app.db import get_db

        async def override_db():
            yield isolated_db

        real_app.dependency_overrides[get_db] = override_db
        creds = b64encode(
            f"{settings.BASIC_AUTH_USER}:{settings.BASIC_AUTH_PASSWORD}".encode()
        ).decode()
        headers = {"Authorization": f"Basic {creds}"}
        try:
            async with AsyncClient(transport=ASGITransport(app=real_app), base_url="http://test", headers=headers) as c:
                resp = await c.get(f"/models/{model.id}")
                assert resp.status_code == 200
                assert 'status-scheduled' in resp.text
                assert 'в расписании' in resp.text
        finally:
            real_app.dependency_overrides.pop(get_db, None)

    @pytest.mark.asyncio
    async def test_single_product_id(self, isolated_db):
        """Single-item list works (per-row 'В расписание' sends [pid])."""
        acc, model, products = await _seed(isolated_db, count=2)
        app = _make_app(isolated_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(f"/models/{model.id}/bulk-schedule", json={
                "product_ids": [products[0].id],
            })

        data = resp.json()
        assert data["ok"] is True
        assert data["scheduled"] == [products[0].id]

        await isolated_db.refresh(products[0])
        assert products[0].status == "scheduled"

        # Second product untouched
        await isolated_db.refresh(products[1])
        assert products[1].status == "draft"

    @pytest.mark.asyncio
    async def test_empty_ids_returns_error(self, isolated_db):
        app = _make_app(isolated_db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/models/1/bulk-schedule", json={"product_ids": []})
        assert resp.status_code == 400
