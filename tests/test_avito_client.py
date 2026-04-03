"""Tests for AvitoClient: token refresh, retry logic, upload_feed multipart."""

import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio

from app.services.avito_client import AvitoClient, MAX_RETRIES_429, MAX_RETRIES_5XX


def _make_account(**kw):
    defaults = {
        "id": 1,
        "name": "Test Account",
        "client_id": "test_id",
        "client_secret": "test_secret",
        "access_token": "valid_token",
        "token_expires_at": datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1),
    }
    defaults.update(kw)
    return MagicMock(**defaults)


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.commit = AsyncMock()
    return db


class TestTokenRefresh:
    @pytest.mark.asyncio
    async def test_uses_existing_valid_token(self, mock_db):
        account = _make_account()
        client = AvitoClient(account, mock_db)
        try:
            await client._ensure_token()
            # Should not call auth endpoint
            assert account.access_token == "valid_token"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_refreshes_expired_token(self, mock_db):
        account = _make_account(
            access_token="old_token",
            token_expires_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1),
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "access_token": "new_token",
            "expires_in": 86400,
        }

        client = AvitoClient(account, mock_db)
        try:
            with patch.object(client._client, "post", return_value=mock_response) as mock_post:
                await client._ensure_token()
                mock_post.assert_called_once()
                assert account.access_token == "new_token"
                mock_db.commit.assert_called_once()
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_refreshes_when_no_token(self, mock_db):
        account = _make_account(access_token=None, token_expires_at=None)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "access_token": "fresh_token",
            "expires_in": 3600,
        }

        client = AvitoClient(account, mock_db)
        try:
            with patch.object(client._client, "post", return_value=mock_response):
                await client._ensure_token()
                assert account.access_token == "fresh_token"
        finally:
            await client.close()


class TestRetryLogic:
    @pytest.mark.asyncio
    async def test_retry_on_429(self, mock_db):
        account = _make_account()
        client = AvitoClient(account, mock_db)

        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.headers = {}
        resp_429.raise_for_status = MagicMock(side_effect=httpx.HTTPStatusError(
            "429", request=MagicMock(), response=resp_429
        ))

        resp_200 = MagicMock()
        resp_200.status_code = 200

        try:
            with patch.object(client._client, "request", side_effect=[resp_429, resp_200]):
                with patch("app.services.avito_client.asyncio.sleep", new_callable=AsyncMock):
                    result = await client._request_with_retry("GET", "https://example.com")
                    assert result.status_code == 200
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_retry_on_503(self, mock_db):
        account = _make_account()
        client = AvitoClient(account, mock_db)

        resp_503 = MagicMock()
        resp_503.status_code = 503
        resp_503.headers = {}
        resp_503.raise_for_status = MagicMock(side_effect=httpx.HTTPStatusError(
            "503", request=MagicMock(), response=resp_503
        ))

        resp_200 = MagicMock()
        resp_200.status_code = 200

        try:
            with patch.object(client._client, "request", side_effect=[resp_503, resp_200]):
                with patch("app.services.avito_client.asyncio.sleep", new_callable=AsyncMock):
                    result = await client._request_with_retry("GET", "https://example.com")
                    assert result.status_code == 200
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_raises_after_max_429_retries(self, mock_db):
        account = _make_account()
        client = AvitoClient(account, mock_db)

        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.headers = {}
        resp_429.raise_for_status = MagicMock(side_effect=httpx.HTTPStatusError(
            "429", request=MagicMock(), response=resp_429
        ))

        try:
            with patch.object(
                client._client, "request",
                side_effect=[resp_429] * (MAX_RETRIES_429 + 1),
            ):
                with patch("app.services.avito_client.asyncio.sleep", new_callable=AsyncMock):
                    with pytest.raises(httpx.HTTPStatusError):
                        await client._request_with_retry("GET", "https://example.com")
        finally:
            await client.close()


class TestUploadFeed:
    @pytest.mark.asyncio
    async def test_upload_sends_multipart(self, mock_db):
        account = _make_account()
        client = AvitoClient(account, mock_db)

        resp = MagicMock()
        resp.status_code = 200
        resp.text = '{"ok": true}'
        resp.json.return_value = {"ok": True}

        try:
            with patch.object(client._client, "request", return_value=resp) as mock_req:
                with patch("app.services.avito_client.asyncio.sleep", new_callable=AsyncMock):
                    result = await client.upload_feed(b"<xml>test</xml>", "feed.xml")
                    assert result == {"ok": True}
                    call_kwargs = mock_req.call_args
                    assert call_kwargs.kwargs.get("files") is not None
                    file_tuple = call_kwargs.kwargs["files"]["file"]
                    assert file_tuple[0] == "feed.xml"
                    assert file_tuple[2] == "application/xml"
        finally:
            await client.close()
