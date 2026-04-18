"""Tests for app/routes/yandex_preview.py — preview image proxy."""

from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import quote

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.db import get_db
from app.routes.yandex_preview import router


def _make_app():
    app = FastAPI()
    app.include_router(router)
    return app


class TestYandexPreview:
    @pytest.mark.asyncio
    async def test_rejects_non_https(self):
        app = _make_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/yandex-preview", params={"url": "http://downloader.disk.yandex.ru/preview/abc"})
        assert resp.status_code == 400
        assert "https" in resp.json()["error"]

    @pytest.mark.asyncio
    async def test_rejects_disallowed_host(self):
        app = _make_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/yandex-preview", params={"url": "https://evil.com/preview/abc"})
        assert resp.status_code == 400
        assert "not allowed" in resp.json()["error"]

    @pytest.mark.asyncio
    async def test_forwards_allowed_host(self):
        fake_jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 100
        mock_resp = httpx.Response(
            200, content=fake_jpeg,
            headers={"content-type": "image/jpeg"},
            request=httpx.Request("GET", "https://mock"),
        )

        app = _make_app()
        with patch("app.routes.yandex_preview.httpx.AsyncClient") as MockClient:
            client_instance = AsyncMock()
            client_instance.get = AsyncMock(return_value=mock_resp)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                resp = await c.get("/api/yandex-preview", params={
                    "url": "https://downloader.disk.yandex.ru/preview/abc123"
                })

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/jpeg"
        assert resp.content == fake_jpeg

    @pytest.mark.asyncio
    async def test_upstream_404_returns_502(self):
        mock_resp = httpx.Response(
            404, content=b"not found",
            request=httpx.Request("GET", "https://mock"),
        )

        app = _make_app()
        with patch("app.routes.yandex_preview.httpx.AsyncClient") as MockClient:
            client_instance = AsyncMock()
            client_instance.get = AsyncMock(return_value=mock_resp)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                resp = await c.get("/api/yandex-preview", params={
                    "url": "https://downloader.disk.yandex.ru/preview/expired"
                })

        assert resp.status_code == 502

    @pytest.mark.asyncio
    async def test_upstream_timeout_returns_504(self):
        app = _make_app()
        with patch("app.routes.yandex_preview.httpx.AsyncClient") as MockClient:
            client_instance = AsyncMock()
            client_instance.get = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
            MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                resp = await c.get("/api/yandex-preview", params={
                    "url": "https://downloader.disk.yandex.ru/preview/slow"
                })

        assert resp.status_code == 504
