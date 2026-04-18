"""Tests for app/services/yandex_disk.py — Yandex.Disk public API client."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.yandex_disk import (
    extract_public_key,
    list_folder,
    get_download_url,
    download_file,
    RateLimitError,
)


# ---------------------------------------------------------------------------
# extract_public_key
# ---------------------------------------------------------------------------

class TestExtractPublicKey:
    def test_valid_disk_yandex_ru(self):
        url = "https://disk.yandex.ru/d/abc123def456"
        assert extract_public_key(url) == url

    def test_valid_yadi_sk(self):
        url = "https://yadi.sk/d/xyz789"
        assert extract_public_key(url) == url

    def test_strips_whitespace(self):
        url = "  https://disk.yandex.ru/d/abc  "
        assert extract_public_key(url) == "https://disk.yandex.ru/d/abc"

    def test_rejects_empty(self):
        with pytest.raises(ValueError, match="Empty"):
            extract_public_key("")

    def test_rejects_non_yandex(self):
        with pytest.raises(ValueError, match="Not a Yandex"):
            extract_public_key("https://google.com/d/something")

    def test_rejects_bad_scheme(self):
        with pytest.raises(ValueError, match="Invalid scheme"):
            extract_public_key("ftp://disk.yandex.ru/d/abc")

    def test_rejects_client_disk_url(self):
        """Personal /client/disk/ URLs must be rejected with a clear Russian message."""
        with pytest.raises(ValueError, match="не публичная ссылка"):
            extract_public_key("https://disk.yandex.ru/client/disk/Папка/Adidas/photo")

    def test_rejects_client_disk_url_encoded(self):
        with pytest.raises(ValueError, match="не публичная ссылка"):
            extract_public_key("https://disk.yandex.ru/client/disk/%D0%9F%D0%B0%D0%BF%D0%BA%D0%B0")

    def test_accepts_i_url(self):
        url = "https://disk.yandex.ru/i/AbCdEf123"
        assert extract_public_key(url) == url

    def test_rejects_short_path(self):
        with pytest.raises(ValueError, match="too short"):
            extract_public_key("https://disk.yandex.ru/d")


# ---------------------------------------------------------------------------
# list_folder (mocked httpx)
# ---------------------------------------------------------------------------

def _mock_response(status_code, json_data=None):
    """Build a mock httpx.Response with a request set."""
    resp = httpx.Response(
        status_code,
        json=json_data or {},
        request=httpx.Request("GET", "https://mock"),
    )
    return resp


def _mock_list_response(items):
    """Build a mock Yandex.Disk API response."""
    return _mock_response(200, {
        "public_key": "https://disk.yandex.ru/d/test",
        "_embedded": {"items": items},
    })


class TestListFolder:
    @pytest.mark.asyncio
    async def test_happy_path(self):
        items = [
            {"type": "file", "name": "photo1.jpg", "path": "/photo1.jpg",
             "size": 12345, "mime_type": "image/jpeg", "md5": "abc123", "preview": "https://preview/1"},
            {"type": "file", "name": "readme.txt", "path": "/readme.txt",
             "size": 100, "mime_type": "text/plain", "md5": "def456", "preview": ""},
            {"type": "dir", "name": "subdir", "path": "/subdir",
             "size": 0, "mime_type": "", "md5": ""},
        ]
        mock_resp = _mock_list_response(items)

        with patch("app.services.yandex_disk.httpx.AsyncClient") as MockClient:
            client_instance = AsyncMock()
            client_instance.get = AsyncMock(return_value=mock_resp)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await list_folder("https://disk.yandex.ru/d/test")

        assert len(result) == 1  # only image files
        assert result[0]["name"] == "photo1.jpg"
        assert result[0]["md5"] == "abc123"

    @pytest.mark.asyncio
    async def test_404_raises_value_error(self):
        mock_resp = _mock_response(404, {"error": "not found"})

        with patch("app.services.yandex_disk.httpx.AsyncClient") as MockClient:
            client_instance = AsyncMock()
            client_instance.get = AsyncMock(return_value=mock_resp)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(ValueError, match="not found"):
                await list_folder("https://disk.yandex.ru/d/test")

    @pytest.mark.asyncio
    async def test_429_raises_rate_limit(self):
        mock_resp = _mock_response(429, {"error": "too many requests"})

        with patch("app.services.yandex_disk.httpx.AsyncClient") as MockClient:
            client_instance = AsyncMock()
            client_instance.get = AsyncMock(return_value=mock_resp)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(RateLimitError):
                await list_folder("https://disk.yandex.ru/d/test")

    @pytest.mark.asyncio
    async def test_sorts_by_name(self):
        items = [
            {"type": "file", "name": "z.jpg", "path": "/z.jpg",
             "size": 1, "mime_type": "image/jpeg", "md5": "z", "preview": ""},
            {"type": "file", "name": "a.jpg", "path": "/a.jpg",
             "size": 1, "mime_type": "image/jpeg", "md5": "a", "preview": ""},
        ]
        mock_resp = _mock_list_response(items)

        with patch("app.services.yandex_disk.httpx.AsyncClient") as MockClient:
            client_instance = AsyncMock()
            client_instance.get = AsyncMock(return_value=mock_resp)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await list_folder("https://disk.yandex.ru/d/test")

        assert result[0]["name"] == "a.jpg"
        assert result[1]["name"] == "z.jpg"


# ---------------------------------------------------------------------------
# get_download_url
# ---------------------------------------------------------------------------

class TestGetDownloadUrl:
    @pytest.mark.asyncio
    async def test_happy_path(self):
        mock_resp = _mock_response(200, {"href": "https://downloader.disk.yandex.net/file123"})

        with patch("app.services.yandex_disk.httpx.AsyncClient") as MockClient:
            client_instance = AsyncMock()
            client_instance.get = AsyncMock(return_value=mock_resp)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            url = await get_download_url("https://disk.yandex.ru/d/test", "/photo.jpg")

        assert url == "https://downloader.disk.yandex.net/file123"

    @pytest.mark.asyncio
    async def test_missing_href_raises(self):
        mock_resp = _mock_response(200, {"no_href": True})

        with patch("app.services.yandex_disk.httpx.AsyncClient") as MockClient:
            client_instance = AsyncMock()
            client_instance.get = AsyncMock(return_value=mock_resp)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(ValueError, match="No download URL"):
                await get_download_url("https://disk.yandex.ru/d/test", "/photo.jpg")


# ---------------------------------------------------------------------------
# download_file
# ---------------------------------------------------------------------------

class TestDownloadFile:
    @pytest.mark.asyncio
    async def test_downloads_to_disk(self, tmp_path):
        dest = str(tmp_path / "output.jpg")
        chunks = [b"chunk1", b"chunk2", b"chunk3"]

        # Mock get_download_url
        with patch("app.services.yandex_disk.get_download_url", new_callable=AsyncMock) as mock_get_url:
            mock_get_url.return_value = "https://download.example.com/file"

            # Mock the streaming download
            mock_stream_resp = AsyncMock()
            mock_stream_resp.raise_for_status = MagicMock()
            mock_stream_resp.aiter_bytes = MagicMock(return_value=_async_iter(chunks))

            mock_stream_cm = AsyncMock()
            mock_stream_cm.__aenter__ = AsyncMock(return_value=mock_stream_resp)
            mock_stream_cm.__aexit__ = AsyncMock(return_value=False)

            with patch("app.services.yandex_disk.httpx.AsyncClient") as MockClient:
                client_instance = AsyncMock()
                client_instance.stream = MagicMock(return_value=mock_stream_cm)
                MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
                MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

                size = await download_file("https://disk.yandex.ru/d/test", "/photo.jpg", dest)

        assert size == len(b"chunk1") + len(b"chunk2") + len(b"chunk3")
        with open(dest, "rb") as f:
            assert f.read() == b"chunk1chunk2chunk3"


async def _async_iter(items):
    for item in items:
        yield item
