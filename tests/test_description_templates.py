"""Tests for description templates: CRUD, validation, list order, page render."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from app.db import get_db
from app.routes.description_templates import router


def _make_app(mock_db):
    app = FastAPI()
    app.include_router(router)

    async def override_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_db
    return app


def _make_template(tid=1, name="Test Template", body="Template body text", created_at=None, updated_at=None):
    from datetime import datetime
    t = MagicMock()
    t.id = tid
    t.name = name
    t.body = body
    t.created_at = created_at or datetime(2026, 4, 18, 12, 0, 0)
    t.updated_at = updated_at or datetime(2026, 4, 18, 12, 0, 0)
    return t


# ── CREATE ──


class TestCreateTemplate:
    @pytest.mark.asyncio
    async def test_create_template_success(self):
        mock_db = AsyncMock()
        mock_db.commit = AsyncMock()
        refreshed = MagicMock()
        refreshed.id = 42

        async def fake_refresh(obj):
            obj.id = 42

        mock_db.refresh = AsyncMock(side_effect=fake_refresh)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/description-templates", json={"name": "My Template", "body": "Hello world"})

        assert resp.status_code == 201
        data = resp.json()
        assert data["ok"] is True
        assert data["id"] == 42

    @pytest.mark.asyncio
    async def test_create_duplicate_name(self):
        from sqlalchemy.exc import IntegrityError
        mock_db = AsyncMock()
        mock_db.commit = AsyncMock(side_effect=IntegrityError("dup", {}, None))
        mock_db.rollback = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/description-templates", json={"name": "Dup", "body": "text"})

        assert resp.status_code == 409
        assert "already exists" in resp.json()["error"]


# ── UPDATE ──


class TestUpdateTemplate:
    @pytest.mark.asyncio
    async def test_update_template_body(self):
        tpl = _make_template()
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=tpl)
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.patch("/api/description-templates/1", json={"body": "Updated body"})

        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert tpl.body == "Updated body"


# ── DELETE ──


class TestDeleteTemplate:
    @pytest.mark.asyncio
    async def test_delete_template_success(self):
        tpl = _make_template()
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=tpl)
        mock_db.delete = AsyncMock()
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.delete("/api/description-templates/1")

        assert resp.status_code == 204
        mock_db.delete.assert_called_once_with(tpl)

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_404(self):
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.delete("/api/description-templates/999")

        assert resp.status_code == 404


# ── LIST ──


class TestListTemplates:
    @pytest.mark.asyncio
    async def test_list_templates_order(self):
        from datetime import datetime
        t1 = _make_template(tid=1, name="Old", updated_at=datetime(2026, 4, 17))
        t2 = _make_template(tid=2, name="New", updated_at=datetime(2026, 4, 18))

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [t2, t1]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/description-templates")

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert len(data["templates"]) == 2
        assert data["templates"][0]["name"] == "New"
        assert data["templates"][1]["name"] == "Old"


# ── VALIDATION ──


class TestValidation:
    @pytest.mark.asyncio
    async def test_name_empty_returns_422(self):
        mock_db = AsyncMock()
        app = _make_app(mock_db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/description-templates", json={"name": "", "body": "text"})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_name_too_long_returns_422(self):
        mock_db = AsyncMock()
        app = _make_app(mock_db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/description-templates", json={"name": "x" * 101, "body": "text"})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_body_empty_returns_422(self):
        mock_db = AsyncMock()
        app = _make_app(mock_db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/description-templates", json={"name": "ok", "body": ""})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_body_too_long_returns_422(self):
        mock_db = AsyncMock()
        app = _make_app(mock_db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/description-templates", json={"name": "ok", "body": "x" * 5001})
        assert resp.status_code == 422


# ── PAGE RENDER ──


class TestSettingsPage:
    @pytest.mark.asyncio
    async def test_get_settings_page_renders(self):
        mock_db = AsyncMock()
        app = _make_app(mock_db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/settings/description-templates")
        assert resp.status_code == 200
        assert "Шаблоны описаний" in resp.text
