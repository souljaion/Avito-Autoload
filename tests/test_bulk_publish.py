"""Tests for bulk publish from /models/{id}/bulk-publish endpoint.

Uses isolated_db because the endpoint calls db.commit().
"""

import os
import re
import uuid
import tempfile
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text, select as sa_select, event

from app.models.account import Account
from app.models.model import Model as ModelORM
from app.models.product import Product as ProductORM
from app.models.product_image import ProductImage
from app.models.listing import Listing
from app.models.description_template import DescriptionTemplate
from app.models.photo_pack import PhotoPack
from app.models.photo_pack_image import PhotoPackImage


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


async def _seed(db, *, with_images=True, count=3, description="Test desc"):
    """Create account, model, template, and N draft products (ready for feed)."""
    await db.execute(text(
        "SELECT setval('accounts_id_seq', GREATEST(nextval('accounts_id_seq'), "
        "(SELECT COALESCE(MAX(id), 0) FROM accounts)))"
    ))
    token = uuid.uuid4().hex[:8]
    acc = Account(name=f"Bulk-{token}", client_id=f"blk-{token}",
                  client_secret="s", feed_token=f"blkft-{token}")
    db.add(acc)
    await db.flush()

    tpl = DescriptionTemplate(name=f"BulkTpl-{token}", body="bulk test body")
    db.add(tpl)
    await db.flush()

    model = ModelORM(
        name=f"BulkModel-{token}", brand="TestBrand",
        category="Одежда, обувь, аксессуары", goods_type="Мужская обувь",
        subcategory="Кроссовки и кеды", goods_subtype="Кроссовки",
    )
    db.add(model)
    await db.flush()

    products = []
    tmp_files = []
    for i in range(count):
        p = ProductORM(
            title=f"BulkProduct-{i}-{token}",
            brand="TestBrand",
            price=3000 + i * 100,
            status="draft",
            account_id=acc.id,
            model_id=model.id,
            category="Одежда, обувь, аксессуары",
            goods_type="Мужская обувь",
            subcategory="Кроссовки и кеды",
            goods_subtype="Кроссовки",
            condition="Новое с биркой",
            description_template_id=tpl.id,
        )
        db.add(p)
        await db.flush()

        if with_images:
            tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
            tmp.write(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
            tmp.close()
            tmp_files.append(tmp.name)

            product_dir = f"./media/products/{p.id}"
            os.makedirs(product_dir, exist_ok=True)
            import shutil
            dest = os.path.join(product_dir, "0_test.jpg")
            shutil.copy2(tmp.name, dest)

            db.add(ProductImage(
                product_id=p.id, url=f"/media/products/{p.id}/0_test.jpg",
                filename="0_test.jpg", sort_order=0, is_main=True,
            ))
            await db.flush()

        db.add(Listing(product_id=p.id, account_id=acc.id, status="draft"))
        await db.flush()
        products.append(p)

    return acc, model, tpl, products, tmp_files


class TestBulkPublish:

    @pytest.mark.asyncio
    async def test_bulk_publish_ready_drafts(self, isolated_db):
        """Test 1: 3 ready drafts → all 3 get status=scheduled."""
        acc, model, tpl, products, tmp_files = await _seed(isolated_db, count=3)
        try:
            app = _make_app(isolated_db)
            pids = [p.id for p in products]

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                resp = await c.post(f"/models/{model.id}/bulk-publish", json={
                    "product_ids": pids,
                })

            assert resp.status_code == 200
            data = resp.json()
            assert data["ok"] is True
            assert data["published"] == 3
            assert len(data["not_ready"]) == 0

            # Verify status and scheduled_at in DB
            for pid in pids:
                p = await isolated_db.get(ProductORM, pid)
                assert p.status == "scheduled"
                assert p.scheduled_at is not None
        finally:
            for f in tmp_files:
                os.unlink(f)

    @pytest.mark.asyncio
    async def test_bulk_publish_includes_in_feed(self, isolated_db):
        """Test 2: published products are in scheduled status (feed includes scheduled)."""
        acc, model, tpl, products, tmp_files = await _seed(isolated_db, count=2)
        try:
            app = _make_app(isolated_db)
            pids = [p.id for p in products]

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                resp = await c.post(f"/models/{model.id}/bulk-publish", json={
                    "product_ids": pids,
                })

            data = resp.json()
            assert data["published"] == 2

            # Verify listings have scheduled status with scheduled_at
            for pid in pids:
                result = await isolated_db.execute(
                    sa_select(Listing).where(Listing.product_id == pid)
                )
                listing = result.scalar_one()
                assert listing.status == "scheduled"
                assert listing.scheduled_at is not None
        finally:
            for f in tmp_files:
                os.unlink(f)

    @pytest.mark.asyncio
    async def test_bulk_publish_mixed_readiness(self, isolated_db):
        """Test 3: 2 ready + 1 missing photos → 2 published, 1 in not_ready."""
        acc, model, tpl, products, tmp_files = await _seed(isolated_db, count=2)
        try:
            # Create a 3rd product WITHOUT images (not ready)
            p_bad = ProductORM(
                title="NoPhotos",
                brand="TestBrand",
                price=5000,
                status="draft",
                account_id=acc.id,
                model_id=model.id,
                category="Одежда, обувь, аксессуары",
                goods_type="Мужская обувь",
                subcategory="Кроссовки и кеды",
                goods_subtype="Кроссовки",
                condition="Новое с биркой",
                description_template_id=tpl.id,
            )
            isolated_db.add(p_bad)
            await isolated_db.flush()
            isolated_db.add(Listing(product_id=p_bad.id, account_id=acc.id, status="draft"))
            await isolated_db.flush()

            app = _make_app(isolated_db)
            pids = [p.id for p in products] + [p_bad.id]

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                resp = await c.post(f"/models/{model.id}/bulk-publish", json={
                    "product_ids": pids,
                })

            data = resp.json()
            assert data["ok"] is True
            assert data["published"] == 2
            assert len(data["not_ready"]) == 1
            assert data["not_ready"][0]["product_id"] == p_bad.id
            assert "Фото" in data["not_ready"][0]["missing"]

            # Bad product stays draft
            p_bad_refreshed = await isolated_db.get(ProductORM, p_bad.id)
            assert p_bad_refreshed.status == "draft"
        finally:
            for f in tmp_files:
                os.unlink(f)

    @pytest.mark.asyncio
    async def test_bulk_publish_skips_non_draft(self, isolated_db):
        """Test 4: non-draft rows are skipped with reason."""
        acc, model, tpl, products, tmp_files = await _seed(isolated_db, count=2)
        try:
            # Set first product to 'active' (non-draft)
            products[0].status = "active"
            await isolated_db.flush()

            app = _make_app(isolated_db)
            pids = [p.id for p in products]

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                resp = await c.post(f"/models/{model.id}/bulk-publish", json={
                    "product_ids": pids,
                })

            data = resp.json()
            assert data["ok"] is True
            assert data["published"] == 1
            assert len(data["skipped"]) == 1
            assert data["skipped"][0]["product_id"] == products[0].id
        finally:
            for f in tmp_files:
                os.unlink(f)

    @pytest.mark.asyncio
    async def test_bulk_publish_no_n_plus_one(self, isolated_db):
        """ADT and Listing queries are batched: at most 1 each regardless of product count."""
        acc, model, tpl, products, tmp_files = await _seed(isolated_db, count=5)
        try:
            app = _make_app(isolated_db)
            pids = [p.id for p in products]

            # Track SQL statements executed during the request
            queries: list[str] = []
            bind = isolated_db.get_bind()

            def _capture(conn, cursor, statement, parameters, context, executemany):
                queries.append(statement)

            event.listen(bind, "before_cursor_execute", _capture)

            try:
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                    resp = await c.post(f"/models/{model.id}/bulk-publish", json={
                        "product_ids": pids,
                    })

                assert resp.status_code == 200
                data = resp.json()
                assert data["published"] == 5

                # Count queries hitting account_description_templates
                adt_queries = [q for q in queries if "account_description_templates" in q.lower()]
                listing_select_queries = [
                    q for q in queries
                    if "listings" in q.lower()
                    and q.strip().upper().startswith("SELECT")
                ]

                assert len(adt_queries) <= 1, (
                    f"Expected ≤1 ADT query, got {len(adt_queries)}: {adt_queries}"
                )
                assert len(listing_select_queries) <= 1, (
                    f"Expected ≤1 Listing SELECT, got {len(listing_select_queries)}: {listing_select_queries}"
                )
            finally:
                event.remove(bind, "before_cursor_execute", _capture)
        finally:
            for f in tmp_files:
                os.unlink(f)
