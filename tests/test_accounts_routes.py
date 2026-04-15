"""Tests for accounts routes."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from app.db import get_db
from app.routes.accounts import router


def _make_app(mock_db):
    app = FastAPI()
    app.include_router(router)

    async def override_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_db
    return app


def _make_account(
    id=1,
    name="TestAccount",
    client_id="test_client_id",
    client_secret="encrypted_secret",
    phone="+79991234567",
    address="Moscow",
    report_email="test@example.com",
    schedule="10:00-20:00",
    autoload_enabled=True,
    avito_sync_minute=15,
    feed_token="abc-123",
):
    acc = MagicMock()
    acc.id = id
    acc.name = name
    acc.client_id = client_id
    acc.client_secret = client_secret
    acc.phone = phone
    acc.address = address
    acc.report_email = report_email
    acc.schedule = schedule
    acc.autoload_enabled = autoload_enabled
    acc.avito_sync_minute = avito_sync_minute
    acc.feed_token = feed_token
    acc.products = []
    acc.feed_exports = []
    acc.autoload_reports = []
    return acc


def _empty_db():
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_result.scalar_one_or_none.return_value = None

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.get = AsyncMock(return_value=None)
    return mock_db


class TestAccountList:
    @pytest.mark.asyncio
    async def test_list_returns_200(self):
        """GET /accounts returns 200 with empty list."""
        mock_db = _empty_db()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/accounts")

        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    @pytest.mark.asyncio
    async def test_list_with_accounts(self):
        """GET /accounts returns 200 when accounts exist."""
        acc = _make_account(id=1, name="Zulla")
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [acc]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/accounts")

        assert resp.status_code == 200
        assert "Zulla" in resp.text


class TestAccountNew:
    @pytest.mark.asyncio
    async def test_new_form_returns_200(self):
        """GET /accounts/new returns form page."""
        mock_db = _empty_db()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/accounts/new")

        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    @pytest.mark.asyncio
    async def test_create_account_redirects(self):
        """POST /accounts/new creates account and redirects."""
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        with patch("app.routes.accounts.encrypt", return_value="encrypted_val"):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/accounts/new",
                    data={
                        "name": "New Account",
                        "client_id": "cid123",
                        "client_secret": "secret123",
                        "phone": "+79990001122",
                        "address": "SPb",
                        "report_email": "r@test.com",
                        "schedule": "09:00-18:00",
                        "autoload_enabled": "1",
                        "avito_sync_minute": "30",
                    },
                    follow_redirects=False,
                )

        assert resp.status_code == 303
        assert "/accounts/" in resp.headers["location"]
        mock_db.add.assert_called_once()
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_account_empty_secret(self):
        """POST /accounts/new with empty secret sets client_secret=None."""
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        with patch("app.routes.accounts.encrypt", return_value="enc") as mock_enc:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/accounts/new",
                    data={
                        "name": "No Secret",
                        "client_id": "",
                        "client_secret": "",
                        "phone": "",
                        "address": "",
                        "report_email": "",
                        "schedule": "",
                        "autoload_enabled": "",
                        "avito_sync_minute": "",
                    },
                    follow_redirects=False,
                )

        assert resp.status_code == 303
        mock_enc.assert_not_called()
        # The account added should have client_secret=None
        added_account = mock_db.add.call_args[0][0]
        assert added_account.client_secret is None


class TestAccountDetail:
    @pytest.mark.asyncio
    async def test_detail_returns_200(self):
        """GET /accounts/{id} returns detail page."""
        acc = _make_account(id=5, name="Detail Test")
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=acc)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/accounts/5")

        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    @pytest.mark.asyncio
    async def test_detail_not_found(self):
        """GET /accounts/{id} returns 404 for missing account."""
        mock_db = _empty_db()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/accounts/9999")

        assert resp.status_code == 404


class TestAccountEdit:
    @pytest.mark.asyncio
    async def test_edit_form_returns_200(self):
        """GET /accounts/{id}/edit returns edit form with decrypted secret."""
        acc = _make_account(id=3, client_secret="encrypted_data")
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=acc)
        app = _make_app(mock_db)

        with patch("app.routes.accounts.decrypt", return_value="plain_secret"):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get("/accounts/3/edit")

        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    @pytest.mark.asyncio
    async def test_edit_form_not_found(self):
        """GET /accounts/{id}/edit returns 404 for missing account."""
        mock_db = _empty_db()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/accounts/9999/edit")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_edit_form_decrypt_failure(self):
        """GET /accounts/{id}/edit gracefully handles decrypt failure."""
        acc = _make_account(id=3, client_secret="bad_encrypted_data")
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=acc)
        app = _make_app(mock_db)

        with patch("app.routes.accounts.decrypt", side_effect=Exception("bad key")):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get("/accounts/3/edit")

        # Should still return 200 with empty decrypted_secret
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_update_account_redirects(self):
        """POST /accounts/{id}/edit updates and redirects."""
        acc = _make_account(id=7)
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=acc)
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        with patch("app.routes.accounts.encrypt", return_value="new_encrypted"):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/accounts/7/edit",
                    data={
                        "name": "Updated Name",
                        "client_id": "new_cid",
                        "client_secret": "new_secret",
                        "phone": "+79998887766",
                        "address": "New Address",
                        "report_email": "new@test.com",
                        "schedule": "08:00-22:00",
                        "autoload_enabled": "1",
                        "avito_sync_minute": "45",
                    },
                    follow_redirects=False,
                )

        assert resp.status_code == 303
        assert "/accounts/7" in resp.headers["location"]
        assert acc.name == "Updated Name"
        assert acc.client_secret == "new_encrypted"
        assert acc.avito_sync_minute == 45
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_account_not_found(self):
        """POST /accounts/{id}/edit returns 404 for missing account."""
        mock_db = _empty_db()
        app = _make_app(mock_db)

        with patch("app.routes.accounts.encrypt", return_value="enc"):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/accounts/9999/edit",
                    data={
                        "name": "X",
                        "client_id": "",
                        "client_secret": "",
                        "phone": "",
                        "address": "",
                        "report_email": "",
                        "schedule": "",
                        "autoload_enabled": "",
                        "avito_sync_minute": "",
                    },
                    follow_redirects=False,
                )

        assert resp.status_code == 404


class TestDescriptionTemplate:
    @pytest.mark.asyncio
    async def test_get_template_empty(self):
        """GET description-template returns empty string when no template exists."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/accounts/1/description-template")

        assert resp.status_code == 200
        assert resp.json() == {"description_template": ""}

    @pytest.mark.asyncio
    async def test_get_template_with_data(self):
        """GET description-template returns existing template text."""
        tpl = MagicMock()
        tpl.description_template = "Hello {brand}"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = tpl

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/accounts/1/description-template")

        assert resp.status_code == 200
        assert resp.json() == {"description_template": "Hello {brand}"}

    @pytest.mark.asyncio
    async def test_patch_template_creates_new(self):
        """PATCH description-template creates template when none exists."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch(
                "/accounts/1/description-template",
                json={"description_template": "New template"},
            )

        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        mock_db.add.assert_called_once()
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_patch_template_updates_existing(self):
        """PATCH description-template updates existing template."""
        tpl = MagicMock()
        tpl.description_template = "Old text"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = tpl

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch(
                "/accounts/1/description-template",
                json={"description_template": "Updated text"},
            )

        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        assert tpl.description_template == "Updated text"
        mock_db.commit.assert_awaited_once()
        # Should NOT call db.add since template already exists
        mock_db.add.assert_not_called()
