"""Tests for model variants CRUD."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
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


class TestCreateVariant:
    @pytest.mark.asyncio
    async def test_model_not_found(self):
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/models/999/variants", json={"name": "Test"})

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_empty_name(self):
        model = MagicMock()
        model.id = 1
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=model)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/models/1/variants", json={"name": ""})

        assert resp.status_code == 400
        assert "Название" in resp.json()["error"]

    @pytest.mark.asyncio
    async def test_create_success(self):
        model = MagicMock()
        model.id = 1

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=model)
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()

        # After commit, variant.id should be set
        added_objects = []
        def capture_add(obj):
            obj.id = 42
            added_objects.append(obj)
        mock_db.add = capture_add

        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/models/1/variants", json={
                "name": "Белый", "size": "42", "price": 5000, "pack_id": 3,
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["name"] == "Белый"
        assert data["size"] == "42"
        assert data["price"] == 5000
        assert data["pack_id"] == 3

    @pytest.mark.asyncio
    async def test_create_minimal(self):
        """Create with only name — size/price/pack_id all None."""
        model = MagicMock()
        model.id = 1
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=model)
        mock_db.add = lambda obj: setattr(obj, 'id', 10)
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/models/1/variants", json={"name": "Default"})

        data = resp.json()
        assert data["ok"] is True
        assert data["size"] is None
        assert data["price"] is None
        assert data["pack_id"] is None


class TestUpdateVariant:
    @pytest.mark.asyncio
    async def test_not_found(self):
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put("/models/1/variants/999", json={"name": "X"})

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_wrong_model(self):
        """Variant belongs to different model → 404."""
        variant = MagicMock()
        variant.model_id = 2  # different from URL model_id=1
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=variant)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put("/models/1/variants/5", json={"name": "X"})

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_empty_name(self):
        variant = MagicMock()
        variant.model_id = 1
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=variant)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put("/models/1/variants/5", json={"name": ""})

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_update_success(self):
        variant = MagicMock()
        variant.id = 5
        variant.model_id = 1
        variant.name = "Old"
        variant.size = "40"
        variant.price = 3000
        variant.pack_id = None
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=variant)
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put("/models/1/variants/5", json={
                "name": "Updated", "size": "43", "price": 6000,
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert variant.name == "Updated"
        assert variant.size == "43"
        assert variant.price == 6000


class TestDeleteVariant:
    @pytest.mark.asyncio
    async def test_not_found(self):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.delete("/models/1/variants/999")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_has_active_products(self):
        """Cannot delete variant with active products."""
        active_product = MagicMock()
        active_product.status = "active"
        active_product.variant_id = 5

        variant = MagicMock()
        variant.id = 5
        variant.model_id = 1
        variant.products = [active_product]

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = variant
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.delete("/models/1/variants/5")

        assert resp.status_code == 400
        assert "активными" in resp.json()["error"]

    @pytest.mark.asyncio
    async def test_delete_success(self):
        """Delete variant with only draft products — succeeds, unlinks products."""
        draft_product = MagicMock()
        draft_product.status = "draft"
        draft_product.variant_id = 5

        variant = MagicMock()
        variant.id = 5
        variant.model_id = 1
        variant.products = [draft_product]

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = variant
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.delete = AsyncMock()
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.delete("/models/1/variants/5")

        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert draft_product.variant_id is None
        mock_db.delete.assert_called_once_with(variant)

    @pytest.mark.asyncio
    async def test_delete_empty_variant(self):
        """Delete variant with no products — succeeds."""
        variant = MagicMock()
        variant.id = 5
        variant.model_id = 1
        variant.products = []

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = variant
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.delete = AsyncMock()
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.delete("/models/1/variants/5")

        assert resp.status_code == 200
        assert resp.json()["ok"] is True
