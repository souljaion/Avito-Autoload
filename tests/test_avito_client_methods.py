"""Tests for AvitoClient methods: get_profile, update_profile, upload_feed,
get_user_items pagination, get_items_stats batching, get_reports, get_report,
get_report_items, refresh_all_tokens, _ensure_token edge cases, _request_with_retry."""

from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.avito_client import (
    AvitoClient,
    refresh_all_tokens,
    MAX_RETRIES_429,
    MAX_RETRIES_5XX,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _make_response(status_code=200, json_data=None, text="", headers=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text or (str(json_data) if json_data else "")
    resp.headers = headers or {}
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            str(status_code), request=MagicMock(), response=resp
        )
    return resp


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.commit = AsyncMock()
    return db


@pytest.fixture
def client_pair(mock_db):
    """Return (AvitoClient, account) with valid token."""
    account = _make_account()
    c = AvitoClient(account, mock_db)
    return c, account


# ---------------------------------------------------------------------------
# _ensure_token edge cases
# ---------------------------------------------------------------------------

class TestEnsureToken:
    @pytest.mark.asyncio
    async def test_raises_when_no_credentials(self, mock_db):
        account = _make_account(
            client_id=None, client_secret=None,
            access_token=None, token_expires_at=None,
        )
        c = AvitoClient(account, mock_db)
        try:
            with pytest.raises(ValueError, match="missing client_id"):
                await c._ensure_token()
        finally:
            await c.close()

    @pytest.mark.asyncio
    async def test_decrypt_fallback(self, mock_db):
        """When decrypt fails, uses raw client_secret."""
        account = _make_account(
            access_token=None, token_expires_at=None,
        )
        token_resp = _make_response(200, {
            "access_token": "new_tok",
            "expires_in": 3600,
        })

        c = AvitoClient(account, mock_db)
        try:
            with patch("app.services.avito_client.decrypt", side_effect=Exception("bad key")):
                with patch.object(c._client, "post", return_value=token_resp):
                    await c._ensure_token()
            assert account.access_token == "new_tok"
        finally:
            await c.close()

    @pytest.mark.asyncio
    async def test_token_expiry_with_tzinfo_none(self, mock_db):
        """token_expires_at without tzinfo should still work."""
        future = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=2)
        account = _make_account(token_expires_at=future)
        c = AvitoClient(account, mock_db)
        try:
            await c._ensure_token()
            # Should not refresh — token is valid
            assert account.access_token == "valid_token"
        finally:
            await c.close()


# ---------------------------------------------------------------------------
# _request_with_retry
# ---------------------------------------------------------------------------

class TestRequestWithRetry:
    @pytest.mark.asyncio
    async def test_429_respects_retry_after_header(self, mock_db):
        account = _make_account()
        c = AvitoClient(account, mock_db)

        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.headers = {"Retry-After": "5"}
        resp_429.raise_for_status = MagicMock(side_effect=httpx.HTTPStatusError(
            "429", request=MagicMock(), response=resp_429
        ))

        resp_200 = _make_response(200, {"ok": True})

        try:
            with patch.object(c._client, "request", side_effect=[resp_429, resp_200]):
                with patch("app.services.avito_client.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                    result = await c._request_with_retry("GET", "https://example.com")
                    assert result.status_code == 200
                    # Wait time should be max(backoff, retry_after) = max(1.0, 5) = 5
                    mock_sleep.assert_called_once_with(5)
        finally:
            await c.close()

    @pytest.mark.asyncio
    async def test_5xx_exhausts_retries(self, mock_db):
        account = _make_account()
        c = AvitoClient(account, mock_db)

        resp_500 = MagicMock()
        resp_500.status_code = 500
        resp_500.headers = {}
        resp_500.raise_for_status = MagicMock(side_effect=httpx.HTTPStatusError(
            "500", request=MagicMock(), response=resp_500
        ))

        try:
            with patch.object(c._client, "request", side_effect=[resp_500] * (MAX_RETRIES_5XX + 1)):
                with patch("app.services.avito_client.asyncio.sleep", new_callable=AsyncMock):
                    with pytest.raises(httpx.HTTPStatusError):
                        await c._request_with_retry("GET", "https://example.com")
        finally:
            await c.close()

    @pytest.mark.asyncio
    async def test_non_retryable_status_returned_immediately(self, mock_db):
        account = _make_account()
        c = AvitoClient(account, mock_db)
        resp_400 = _make_response(400, {"error": "bad request"})
        # 400 should not retry — just return the response
        resp_400.raise_for_status = MagicMock()  # don't raise

        try:
            with patch.object(c._client, "request", return_value=resp_400):
                result = await c._request_with_retry("GET", "https://example.com")
                assert result.status_code == 400
        finally:
            await c.close()

    @pytest.mark.asyncio
    async def test_exponential_backoff_on_multiple_retries(self, mock_db):
        account = _make_account()
        c = AvitoClient(account, mock_db)

        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.headers = {}
        resp_429.raise_for_status = MagicMock(side_effect=httpx.HTTPStatusError(
            "429", request=MagicMock(), response=resp_429
        ))
        resp_200 = _make_response(200)

        try:
            with patch.object(c._client, "request", side_effect=[resp_429, resp_429, resp_200]):
                with patch("app.services.avito_client.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                    await c._request_with_retry("GET", "https://example.com")
                    # attempt 1: wait = 1.0 * 2^0 = 1.0; attempt 2: wait = 1.0 * 2^1 = 2.0
                    calls = [c.args[0] for c in mock_sleep.call_args_list]
                    assert calls == [1.0, 2.0]
        finally:
            await c.close()


# ---------------------------------------------------------------------------
# get_profile
# ---------------------------------------------------------------------------

class TestGetProfile:
    @pytest.mark.asyncio
    async def test_get_profile(self, client_pair):
        c, account = client_pair
        profile_data = {"autoload_enabled": True, "schedule": []}
        try:
            with patch.object(c, "_request_with_retry", new_callable=AsyncMock,
                              return_value=_make_response(200, profile_data)):
                result = await c.get_profile()
                assert result == profile_data
        finally:
            await c.close()


# ---------------------------------------------------------------------------
# update_profile
# ---------------------------------------------------------------------------

class TestUpdateProfile:
    @pytest.mark.asyncio
    async def test_update_profile_success(self, client_pair):
        c, account = client_pair
        current_profile = {"autoload_enabled": True, "schedule": [], "report_email": "a@b.com"}
        updated_profile = {**current_profile, "feeds_data": [{"feed_name": "my", "feed_url": "http://f.xml"}]}

        resp_get = _make_response(200, current_profile)
        resp_post = _make_response(200, {"ok": True})
        resp_get2 = _make_response(200, updated_profile)

        try:
            with patch.object(c, "_request_with_retry", new_callable=AsyncMock,
                              side_effect=[resp_get, resp_post, resp_get2]):
                result = await c.update_profile("http://f.xml", "my")
                assert result == updated_profile
        finally:
            await c.close()

    @pytest.mark.asyncio
    async def test_update_profile_400_raises_valueerror(self, client_pair):
        c, account = client_pair
        current_profile = {"autoload_enabled": True, "schedule": []}
        resp_get = _make_response(200, current_profile)
        resp_400 = MagicMock()
        resp_400.status_code = 400
        resp_400.json.return_value = {"error": {"message": "bad feed"}}
        resp_400.raise_for_status = MagicMock()

        try:
            with patch.object(c, "_request_with_retry", new_callable=AsyncMock,
                              side_effect=[resp_get, resp_400]):
                with pytest.raises(ValueError, match="Avito отклонил"):
                    await c.update_profile("http://bad.xml")
        finally:
            await c.close()


# ---------------------------------------------------------------------------
# get_user_items (pagination)
# ---------------------------------------------------------------------------

class TestGetUserItems:
    @pytest.mark.asyncio
    async def test_single_page(self, client_pair):
        c, _ = client_pair
        items = [{"id": 1}, {"id": 2}]
        resp = _make_response(200, {"resources": items})

        try:
            with patch.object(c, "_request_with_retry", new_callable=AsyncMock, return_value=resp):
                result = await c.get_user_items(per_page=50)
                assert result == items
        finally:
            await c.close()

    @pytest.mark.asyncio
    async def test_multi_page_pagination(self, client_pair):
        c, _ = client_pair
        page1 = [{"id": i} for i in range(50)]
        page2 = [{"id": i} for i in range(50, 75)]

        resp1 = _make_response(200, {"resources": page1})
        resp2 = _make_response(200, {"resources": page2})

        try:
            with patch.object(c, "_request_with_retry", new_callable=AsyncMock,
                              side_effect=[resp1, resp2]):
                result = await c.get_user_items(per_page=50)
                assert len(result) == 75
        finally:
            await c.close()

    @pytest.mark.asyncio
    async def test_empty_resources(self, client_pair):
        c, _ = client_pair
        resp = _make_response(200, {"resources": []})

        try:
            with patch.object(c, "_request_with_retry", new_callable=AsyncMock, return_value=resp):
                result = await c.get_user_items()
                assert result == []
        finally:
            await c.close()


# ---------------------------------------------------------------------------
# get_items_stats (batching)
# ---------------------------------------------------------------------------

class TestGetItemsStats:
    @pytest.mark.asyncio
    async def test_single_batch(self, client_pair):
        c, _ = client_pair
        resp = _make_response(200, {
            "result": {
                "items": [
                    {
                        "itemId": 111,
                        "stats": [
                            {"uniqViews": 10, "uniqContacts": 2, "uniqFavorites": 1},
                            {"uniqViews": 5, "uniqContacts": 0, "uniqFavorites": 3},
                        ],
                    }
                ]
            }
        })

        try:
            with patch.object(c, "_request_with_retry", new_callable=AsyncMock, return_value=resp):
                result = await c.get_items_stats(user_id=100, avito_ids=[111])
                assert result[111] == {"views": 15, "contacts": 2, "favorites": 4}
        finally:
            await c.close()

    @pytest.mark.asyncio
    async def test_multiple_batches(self, client_pair):
        c, _ = client_pair
        # 250 IDs -> 2 batches (200 + 50)
        ids = list(range(1, 251))

        resp1 = _make_response(200, {"result": {"items": [
            {"itemId": i, "stats": [{"uniqViews": 1, "uniqContacts": 0, "uniqFavorites": 0}]}
            for i in range(1, 201)
        ]}})
        resp2 = _make_response(200, {"result": {"items": [
            {"itemId": i, "stats": [{"uniqViews": 1, "uniqContacts": 0, "uniqFavorites": 0}]}
            for i in range(201, 251)
        ]}})

        try:
            with patch.object(c, "_request_with_retry", new_callable=AsyncMock,
                              side_effect=[resp1, resp2]):
                result = await c.get_items_stats(user_id=100, avito_ids=ids)
                assert len(result) == 250
        finally:
            await c.close()


# ---------------------------------------------------------------------------
# get_reports / get_report / get_report_items
# ---------------------------------------------------------------------------

class TestReports:
    @pytest.mark.asyncio
    async def test_get_reports(self, client_pair):
        c, _ = client_pair
        data = {"reports": [{"id": 1, "status": "done"}]}
        try:
            with patch.object(c, "_request_with_retry", new_callable=AsyncMock,
                              return_value=_make_response(200, data)):
                result = await c.get_reports()
                assert result == data
        finally:
            await c.close()

    @pytest.mark.asyncio
    async def test_get_report(self, client_pair):
        c, _ = client_pair
        data = {"id": 42, "status": "done", "items_count": 10}
        try:
            with patch.object(c, "_request_with_retry", new_callable=AsyncMock,
                              return_value=_make_response(200, data)):
                result = await c.get_report(42)
                assert result == data
        finally:
            await c.close()

    @pytest.mark.asyncio
    async def test_get_report_items(self, client_pair):
        c, _ = client_pair
        data = {"items": [{"ad_id": "1", "status": "active"}]}
        try:
            with patch.object(c, "_request_with_retry", new_callable=AsyncMock,
                              return_value=_make_response(200, data)):
                result = await c.get_report_items(42, page=0)
                assert result == data
        finally:
            await c.close()


# ---------------------------------------------------------------------------
# upload_feed
# ---------------------------------------------------------------------------

class TestUploadFeed:
    @pytest.mark.asyncio
    async def test_upload_feed_429_raises_valueerror(self, mock_db):
        account = _make_account()
        c = AvitoClient(account, mock_db)

        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.text = '{"error": {"message": "already running"}}'
        resp_429.json.return_value = {"error": {"message": "already running"}}
        resp_429.headers = {}

        try:
            with patch.object(c, "_request_with_retry", new_callable=AsyncMock, return_value=resp_429):
                with pytest.raises(ValueError, match="already running"):
                    await c.upload_feed(b"<xml/>")
        finally:
            await c.close()

    @pytest.mark.asyncio
    async def test_upload_feed_401_raises(self, mock_db):
        account = _make_account()
        c = AvitoClient(account, mock_db)

        resp_401 = MagicMock()
        resp_401.status_code = 401
        resp_401.text = ""
        resp_401.json.return_value = {}
        resp_401.headers = {}

        try:
            with patch.object(c, "_request_with_retry", new_callable=AsyncMock, return_value=resp_401):
                with pytest.raises(ValueError, match="401"):
                    await c.upload_feed(b"<xml/>")
        finally:
            await c.close()


# ---------------------------------------------------------------------------
# delete_ad
# ---------------------------------------------------------------------------

class TestDeleteAd:
    @pytest.mark.asyncio
    async def test_delete_ad_404_returns_ok(self, client_pair):
        c, _ = client_pair
        resp_404 = MagicMock()
        resp_404.status_code = 404
        resp_404.raise_for_status = MagicMock()

        try:
            with patch.object(c, "_request_with_retry", new_callable=AsyncMock, return_value=resp_404):
                result = await c.delete_ad(123)
                assert result["ok"] is True
        finally:
            await c.close()

    @pytest.mark.asyncio
    async def test_delete_ad_success(self, client_pair):
        c, _ = client_pair
        resp = MagicMock()
        resp.status_code = 200
        resp.text = '{"ok": true}'
        resp.json.return_value = {"ok": True}
        resp.raise_for_status = MagicMock()

        try:
            with patch.object(c, "_request_with_retry", new_callable=AsyncMock, return_value=resp):
                result = await c.delete_ad(123)
                assert result == {"ok": True}
        finally:
            await c.close()


# ---------------------------------------------------------------------------
# refresh_token
# ---------------------------------------------------------------------------

class TestRefreshToken:
    @pytest.mark.asyncio
    async def test_skips_when_token_fresh(self, mock_db):
        account = _make_account(
            token_expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1),
        )
        c = AvitoClient(account, mock_db)
        try:
            with patch.object(c, "_ensure_token", new_callable=AsyncMock) as mock_ensure:
                await c.refresh_token()
                mock_ensure.assert_not_called()
        finally:
            await c.close()

    @pytest.mark.asyncio
    async def test_refreshes_when_expiring_soon(self, mock_db):
        account = _make_account(
            token_expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=5),
        )
        c = AvitoClient(account, mock_db)
        try:
            with patch.object(c, "_ensure_token", new_callable=AsyncMock) as mock_ensure:
                await c.refresh_token()
                mock_ensure.assert_called_once()
        finally:
            await c.close()


# ---------------------------------------------------------------------------
# refresh_all_tokens
# ---------------------------------------------------------------------------

class TestRefreshAllTokens:
    @pytest.mark.asyncio
    async def test_refreshes_all_accounts(self):
        acc1 = _make_account(name="Acc1")
        acc2 = _make_account(name="Acc2")

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [acc1, acc2]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        with patch("app.services.avito_client.AvitoClient") as MockClient:
            instance = AsyncMock()
            instance.refresh_token = AsyncMock()
            instance.close = AsyncMock()
            MockClient.return_value = instance

            result = await refresh_all_tokens(mock_db)
            assert result == {"refreshed": 2, "errors": 0}

    @pytest.mark.asyncio
    async def test_counts_errors(self):
        acc1 = _make_account(name="Acc1")

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [acc1]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.services.avito_client.AvitoClient") as MockClient:
            instance = AsyncMock()
            instance.refresh_token = AsyncMock(side_effect=Exception("fail"))
            instance.close = AsyncMock()
            MockClient.return_value = instance

            result = await refresh_all_tokens(mock_db)
            assert result == {"refreshed": 0, "errors": 1}
            instance.close.assert_called_once()


# ---------------------------------------------------------------------------
# get_items_info (batching)
# ---------------------------------------------------------------------------

class TestGetItemsInfo:
    @pytest.mark.asyncio
    async def test_single_batch(self, client_pair):
        c, _ = client_pair
        items = [{"ad_id": "1", "avito_status": "active"}]
        resp = _make_response(200, {"items": items})

        try:
            with patch.object(c, "_request_with_retry", new_callable=AsyncMock, return_value=resp):
                result = await c.get_items_info(["1", "2"])
                assert result == items
        finally:
            await c.close()


# ---------------------------------------------------------------------------
# get_report_fees (pagination)
# ---------------------------------------------------------------------------

class TestGetReportFees:
    @pytest.mark.asyncio
    async def test_single_page(self, client_pair):
        c, _ = client_pair
        fees_data = {"fees": [{"ad_id": "1", "fee": 100}], "meta": {"pages": 1}}
        resp = _make_response(200, fees_data)

        try:
            with patch.object(c, "_request_with_retry", new_callable=AsyncMock, return_value=resp):
                result = await c.get_report_fees(42)
                assert result["total"] == 1
                assert len(result["fees"]) == 1
        finally:
            await c.close()

    @pytest.mark.asyncio
    async def test_multi_page(self, client_pair):
        c, _ = client_pair
        resp1 = _make_response(200, {"fees": [{"ad_id": "1"}], "meta": {"pages": 2}})
        resp2 = _make_response(200, {"fees": [{"ad_id": "2"}], "meta": {"pages": 2}})

        try:
            with patch.object(c, "_request_with_retry", new_callable=AsyncMock,
                              side_effect=[resp1, resp2]):
                result = await c.get_report_fees(42)
                assert result["total"] == 2
        finally:
            await c.close()

    @pytest.mark.asyncio
    async def test_error_returns_empty(self, client_pair):
        c, _ = client_pair
        try:
            with patch.object(c, "_request_with_retry", new_callable=AsyncMock,
                              side_effect=Exception("network")):
                result = await c.get_report_fees(42)
                assert result == {"fees": [], "total": 0, "report_id": 42}
        finally:
            await c.close()
