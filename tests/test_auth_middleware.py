"""Tests for app/middleware/auth.py — BasicAuthMiddleware."""

from base64 import b64encode

import pytest
from fastapi import FastAPI, Request
from httpx import AsyncClient, ASGITransport

from app.config import settings
from app.middleware.auth import BasicAuthMiddleware, _is_public


def _make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(BasicAuthMiddleware)

    @app.get("/protected")
    async def protected(request: Request):
        return {"ok": True, "auth_b64": request.state.auth_b64}

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/feeds/{name}.xml")
    async def feed(name: str):
        return {"feed": name}

    @app.get("/media/{path:path}")
    async def media(path: str):
        return {"path": path}

    @app.get("/static/{path:path}")
    async def static(path: str):
        return {"path": path}

    return app


def _basic(user: str, password: str) -> dict[str, str]:
    creds = b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {creds}"}


@pytest.fixture
def app():
    return _make_app()


@pytest.fixture
async def http(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# _is_public helper
# ---------------------------------------------------------------------------

class TestIsPublic:
    def test_health_is_public(self):
        assert _is_public("/health") is True

    def test_feeds_xml_is_public(self):
        assert _is_public("/feeds/anything.xml") is True
        assert _is_public("/feeds/123.xml") is True

    def test_feeds_non_xml_is_not_public(self):
        assert _is_public("/feeds/list") is False
        assert _is_public("/feeds/index.html") is False

    def test_media_is_public(self):
        assert _is_public("/media/file.jpg") is True
        assert _is_public("/media/sub/dir/file.png") is True

    def test_static_is_public(self):
        assert _is_public("/static/app.js") is True
        assert _is_public("/static/css/style.css") is True

    def test_random_path_is_not_public(self):
        assert _is_public("/products") is False
        assert _is_public("/api/listings") is False
        assert _is_public("/") is False


# ---------------------------------------------------------------------------
# Successful auth
# ---------------------------------------------------------------------------

class TestSuccessfulAuth:
    @pytest.mark.asyncio
    async def test_correct_credentials_pass(self, http):
        resp = await http.get(
            "/protected",
            headers=_basic(settings.BASIC_AUTH_USER, settings.BASIC_AUTH_PASSWORD),
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    @pytest.mark.asyncio
    async def test_auth_b64_set_on_success(self, http):
        resp = await http.get(
            "/protected",
            headers=_basic(settings.BASIC_AUTH_USER, settings.BASIC_AUTH_PASSWORD),
        )
        assert resp.status_code == 200
        expected = b64encode(
            f"{settings.BASIC_AUTH_USER}:{settings.BASIC_AUTH_PASSWORD}".encode()
        ).decode()
        assert resp.json()["auth_b64"] == expected


# ---------------------------------------------------------------------------
# Failed auth
# ---------------------------------------------------------------------------

class TestFailedAuth:
    @pytest.mark.asyncio
    async def test_no_authorization_header_returns_401(self, http):
        resp = await http.get("/protected")
        assert resp.status_code == 401
        assert "WWW-Authenticate" in resp.headers
        assert resp.headers["WWW-Authenticate"].startswith("Basic")

    @pytest.mark.asyncio
    async def test_wrong_password_returns_401(self, http):
        resp = await http.get(
            "/protected",
            headers=_basic(settings.BASIC_AUTH_USER, "wrong-password"),
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_wrong_username_returns_401(self, http):
        resp = await http.get(
            "/protected",
            headers=_basic("nobody", settings.BASIC_AUTH_PASSWORD),
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_both_wrong_returns_401(self, http):
        resp = await http.get(
            "/protected",
            headers=_basic("nobody", "wrong"),
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_non_basic_scheme_returns_401(self, http):
        resp = await http.get(
            "/protected",
            headers={"Authorization": "Bearer token-here"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_malformed_base64_returns_401(self, http):
        resp = await http.get(
            "/protected",
            headers={"Authorization": "Basic !!!not-base64!!!"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_credentials_without_colon_returns_401(self, http):
        # "useronly" without ":" → ValueError on split
        bad = b64encode(b"useronly").decode()
        resp = await http.get(
            "/protected",
            headers={"Authorization": f"Basic {bad}"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_invalid_utf8_returns_401(self, http):
        # Bytes that are not valid UTF-8
        bad = b64encode(b"\xff\xfe\xfd").decode()
        resp = await http.get(
            "/protected",
            headers={"Authorization": f"Basic {bad}"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Public paths bypass auth
# ---------------------------------------------------------------------------

class TestPublicPathsBypass:
    @pytest.mark.asyncio
    async def test_health_no_auth(self, http):
        resp = await http.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    @pytest.mark.asyncio
    async def test_feeds_xml_no_auth(self, http):
        resp = await http.get("/feeds/anything.xml")
        assert resp.status_code == 200
        assert resp.json()["feed"] == "anything"

    @pytest.mark.asyncio
    async def test_media_no_auth(self, http):
        resp = await http.get("/media/file.jpg")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_static_no_auth(self, http):
        resp = await http.get("/static/app.js")
        assert resp.status_code == 200
