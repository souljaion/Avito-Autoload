"""Tests for Bug #5: photo pack not applied when creating products
from /models/{id} matrix row (addNewRow → create_model_product).

Tests use isolated_db because the endpoint calls db.commit().
"""

import os
import uuid
import tempfile

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text, select as sa_select

from app.models.account import Account
from app.models.model import Model as ModelORM
from app.models.product import Product as ProductORM
from app.models.product_image import ProductImage
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


async def _seed(db):
    """Create account + model for tests. Returns (account, model)."""
    await db.execute(text(
        "SELECT setval('accounts_id_seq', GREATEST(nextval('accounts_id_seq'), "
        "(SELECT COALESCE(MAX(id), 0) FROM accounts)))"
    ))
    token = uuid.uuid4().hex[:8]
    acc = Account(name=f"Bug5-{token}", client_id=f"b5-{token}",
                  client_secret="s", feed_token=f"b5ft-{token}")
    db.add(acc)
    await db.flush()

    model = ModelORM(
        name=f"Bug5Model-{token}", brand="TestBrand",
        category="Одежда, обувь, аксессуары", goods_type="Мужская обувь",
        subcategory="Кроссовки и кеды", goods_subtype="Кроссовки",
    )
    db.add(model)
    await db.flush()
    return acc, model


class TestCreateModelProductPack:
    """Bug #5: pack_id from matrix row must be applied to new product."""

    @pytest.mark.asyncio
    async def test_pack_applied_creates_product_images(self, isolated_db):
        """POST with pack_id → product has images from that pack."""
        acc, model = await _seed(isolated_db)

        pack = PhotoPack(name="TestPack", model_id=model.id)
        isolated_db.add(pack)
        await isolated_db.flush()

        # Create a real temp file so _apply_pack_to_product finds it on disk
        tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        tmp.write(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
        tmp.close()
        try:
            isolated_db.add(PhotoPackImage(
                pack_id=pack.id, file_path=tmp.name,
                url="/media/packs/test.jpg", sort_order=0,
            ))
            await isolated_db.flush()

            app = _make_app(isolated_db)
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                resp = await c.post(f"/models/{model.id}/products", json={
                    "account_id": acc.id,
                    "size": "42",
                    "price": 3790,
                    "pack_id": pack.id,
                })

            assert resp.status_code == 200
            data = resp.json()
            assert data["ok"] is True

            # Verify product_images were created from pack
            result = await isolated_db.execute(
                sa_select(ProductImage).where(
                    ProductImage.product_id == data["product_id"]
                )
            )
            images = result.scalars().all()
            assert len(images) == 1
            assert images[0].is_main is True
        finally:
            os.unlink(tmp.name)

    @pytest.mark.asyncio
    async def test_no_pack_creates_no_images(self, isolated_db):
        """POST without pack_id → product has no product_images."""
        acc, model = await _seed(isolated_db)

        app = _make_app(isolated_db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(f"/models/{model.id}/products", json={
                "account_id": acc.id,
                "size": "43",
                "price": 4000,
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True

        result = await isolated_db.execute(
            sa_select(ProductImage).where(
                ProductImage.product_id == data["product_id"]
            )
        )
        images = result.scalars().all()
        assert len(images) == 0


class TestCreateModelProductPrice:
    """Model.price is copied to Product.price on creation."""

    @pytest.mark.asyncio
    async def test_model_price_copied_to_product(self, isolated_db):
        """Product inherits model.price when no explicit price in request."""
        acc, model = await _seed(isolated_db)
        model.price = 7000
        await isolated_db.flush()

        app = _make_app(isolated_db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(f"/models/{model.id}/products", json={
                "account_id": acc.id,
            })

        assert resp.status_code == 200
        pid = resp.json()["product_id"]
        product = await isolated_db.get(ProductORM, pid)
        assert product.price == 7000

    @pytest.mark.asyncio
    async def test_explicit_price_overrides_model(self, isolated_db):
        """Explicit price in request overrides model.price."""
        acc, model = await _seed(isolated_db)
        model.price = 7000
        await isolated_db.flush()

        app = _make_app(isolated_db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(f"/models/{model.id}/products", json={
                "account_id": acc.id,
                "price": 8000,
            })

        assert resp.status_code == 200
        pid = resp.json()["product_id"]
        product = await isolated_db.get(ProductORM, pid)
        assert product.price == 8000

    @pytest.mark.asyncio
    async def test_null_model_price_no_product_price(self, isolated_db):
        """Model.price=None → Product.price=None."""
        acc, model = await _seed(isolated_db)
        # model.price is None by default

        app = _make_app(isolated_db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(f"/models/{model.id}/products", json={
                "account_id": acc.id,
            })

        assert resp.status_code == 200
        pid = resp.json()["product_id"]
        product = await isolated_db.get(ProductORM, pid)
        assert product.price is None


class TestPackIdPersistence:
    """Regression: creating a second draft must not reset pack_id on the first."""

    @pytest.mark.asyncio
    async def test_pack_id_saved_on_product(self, isolated_db):
        """POST with pack_id → product.pack_id is persisted in DB."""
        acc, model = await _seed(isolated_db)

        pack = PhotoPack(name="PersistPack", model_id=model.id)
        isolated_db.add(pack)
        await isolated_db.flush()

        app = _make_app(isolated_db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(f"/models/{model.id}/products", json={
                "account_id": acc.id,
                "size": "42",
                "price": 5000,
                "pack_id": pack.id,
            })

        assert resp.status_code == 200
        pid = resp.json()["product_id"]
        product = await isolated_db.get(ProductORM, pid)
        assert product.pack_id == pack.id

    @pytest.mark.asyncio
    async def test_second_draft_does_not_reset_first_pack_id(self, isolated_db):
        """Creating a second draft must not clear pack_id on the first draft."""
        acc, model = await _seed(isolated_db)

        # Second account for the second draft
        token2 = uuid.uuid4().hex[:8]
        acc2 = Account(name=f"Acc2-{token2}", client_id=f"a2-{token2}",
                       client_secret="s", feed_token=f"a2ft-{token2}")
        isolated_db.add(acc2)
        await isolated_db.flush()

        pack = PhotoPack(name="StablePack", model_id=model.id)
        isolated_db.add(pack)
        await isolated_db.flush()

        app = _make_app(isolated_db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            # Create first draft with pack
            resp1 = await c.post(f"/models/{model.id}/products", json={
                "account_id": acc.id,
                "size": "42",
                "price": 5000,
                "pack_id": pack.id,
            })
            assert resp1.status_code == 200
            pid1 = resp1.json()["product_id"]

            # Create second draft (different account, no pack)
            resp2 = await c.post(f"/models/{model.id}/products", json={
                "account_id": acc2.id,
                "size": "43",
                "price": 6000,
            })
            assert resp2.status_code == 200

        # First product must still have its pack_id
        await isolated_db.refresh(await isolated_db.get(ProductORM, pid1))
        product1 = await isolated_db.get(ProductORM, pid1)
        assert product1.pack_id == pack.id, (
            f"pack_id was reset to {product1.pack_id} after creating second draft"
        )

    @pytest.mark.asyncio
    async def test_pack_dropdown_selected_in_template(self, isolated_db):
        """After reload, the pack dropdown shows the saved pack as selected."""
        from base64 import b64encode
        from app.config import settings

        acc, model = await _seed(isolated_db)

        pack = PhotoPack(name="VisiblePack", model_id=model.id)
        isolated_db.add(pack)
        await isolated_db.flush()

        # Use the real app (with Jinja2 templates and auth middleware)
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
                # Create draft with pack
                resp = await c.post(f"/models/{model.id}/products", json={
                    "account_id": acc.id,
                    "pack_id": pack.id,
                })
                assert resp.status_code == 200

                # Load the model detail page
                detail_resp = await c.get(f"/models/{model.id}")
                assert detail_resp.status_code == 200
                html = detail_resp.text

                # The pack name should appear in the product card
                assert "VisiblePack" in html, (
                    "Pack name not visible in product card after page reload"
                )
        finally:
            real_app.dependency_overrides.pop(get_db, None)
