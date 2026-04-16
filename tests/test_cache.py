"""Tests for app/cache.py — TTL cache + integration with get_report_fees."""

import asyncio
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.cache import TTLCache, cache as global_cache


# ---------------------------------------------------------------------------
# TTLCache primitives
# ---------------------------------------------------------------------------

class TestTTLCache:
    @pytest.mark.asyncio
    async def test_get_missing_returns_none(self):
        c = TTLCache()
        assert await c.get("nope") is None

    @pytest.mark.asyncio
    async def test_set_then_get(self):
        c = TTLCache()
        await c.set("k", {"x": 1}, ttl_seconds=60)
        assert await c.get("k") == {"x": 1}

    @pytest.mark.asyncio
    async def test_expired_get_returns_none(self):
        c = TTLCache()
        await c.set("k", "v", ttl_seconds=60)
        # Fake the clock by patching time.monotonic
        future = time.monotonic() + 120
        with patch("app.cache.time.monotonic", return_value=future):
            assert await c.get("k") is None
        # Expired entry is also removed
        assert await c.size() == 0

    @pytest.mark.asyncio
    async def test_zero_or_negative_ttl_is_noop(self):
        c = TTLCache()
        await c.set("k", "v", ttl_seconds=0)
        assert await c.get("k") is None
        await c.set("k", "v", ttl_seconds=-5)
        assert await c.get("k") is None

    @pytest.mark.asyncio
    async def test_invalidate_removes_key(self):
        c = TTLCache()
        await c.set("k", "v", ttl_seconds=60)
        await c.invalidate("k")
        assert await c.get("k") is None
        # Invalidating a missing key is silent
        await c.invalidate("never-existed")

    @pytest.mark.asyncio
    async def test_clear_drops_everything(self):
        c = TTLCache()
        await c.set("a", 1, ttl_seconds=60)
        await c.set("b", 2, ttl_seconds=60)
        assert await c.size() == 2
        await c.clear()
        assert await c.size() == 0
        assert await c.get("a") is None

    @pytest.mark.asyncio
    async def test_overwrite_extends_ttl(self):
        c = TTLCache()
        await c.set("k", "old", ttl_seconds=60)
        await c.set("k", "new", ttl_seconds=120)
        assert await c.get("k") == "new"

    @pytest.mark.asyncio
    async def test_concurrent_writes_are_safe(self):
        """No exceptions or lost writes when many coroutines hit the lock."""
        c = TTLCache()

        async def worker(i):
            await c.set(f"k{i}", i, ttl_seconds=60)

        await asyncio.gather(*(worker(i) for i in range(50)))
        for i in range(50):
            assert await c.get(f"k{i}") == i


# ---------------------------------------------------------------------------
# get_report_fees caching integration
# ---------------------------------------------------------------------------

def _make_account(id=1):
    acc = MagicMock()
    acc.id = id
    acc.name = "TestAcc"
    acc.client_id = "cid"
    acc.client_secret = "sec"
    acc.access_token = "tok"
    acc.token_expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1)
    return acc


def _make_response(json_data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


class TestGetReportFeesCaching:
    @pytest.mark.asyncio
    async def test_second_call_uses_cache(self):
        """Once cached, subsequent calls skip the HTTP request entirely."""
        from app.services.avito_client import AvitoClient

        await global_cache.clear()
        try:
            account = _make_account(id=42)
            db = AsyncMock()

            client = AvitoClient(account, db)

            api_resp = _make_response({"fees": [{"amount_total": 100}], "meta": {"pages": 1}})
            client._request_with_retry = AsyncMock(return_value=api_resp)
            client._headers = AsyncMock(return_value={})

            # First call → API
            r1 = await client.get_report_fees(report_id=999, report_status="completed")
            assert r1["total"] == 1
            assert client._request_with_retry.call_count == 1

            # Second call → cache, no new API call
            r2 = await client.get_report_fees(report_id=999, report_status="completed")
            assert r2 == r1
            assert client._request_with_retry.call_count == 1
        finally:
            await global_cache.clear()

    @pytest.mark.asyncio
    async def test_completed_report_caches_for_24h(self):
        """status=completed → TTL = 86400s."""
        from app.services.avito_client import AvitoClient

        await global_cache.clear()
        try:
            account = _make_account(id=7)
            db = AsyncMock()
            client = AvitoClient(account, db)
            client._request_with_retry = AsyncMock(
                return_value=_make_response({"fees": [], "meta": {"pages": 1}})
            )
            client._headers = AsyncMock(return_value={})

            with patch("app.cache.cache.set", new=AsyncMock()) as mock_set:
                await client.get_report_fees(report_id=1, report_status="completed")
                mock_set.assert_called_once()
                _, kwargs = mock_set.call_args
                assert kwargs["ttl_seconds"] == 24 * 3600
        finally:
            await global_cache.clear()

    @pytest.mark.asyncio
    async def test_unfinished_report_caches_for_5min(self):
        """status=processing → TTL = 300s."""
        from app.services.avito_client import AvitoClient

        await global_cache.clear()
        try:
            account = _make_account(id=8)
            db = AsyncMock()
            client = AvitoClient(account, db)
            client._request_with_retry = AsyncMock(
                return_value=_make_response({"fees": [], "meta": {"pages": 1}})
            )
            client._headers = AsyncMock(return_value={})

            with patch("app.cache.cache.set", new=AsyncMock()) as mock_set:
                await client.get_report_fees(report_id=2, report_status="processing")
                _, kwargs = mock_set.call_args
                assert kwargs["ttl_seconds"] == 5 * 60
        finally:
            await global_cache.clear()

    @pytest.mark.asyncio
    async def test_unknown_status_caches_for_5min(self):
        """No status passed → conservative 5min TTL."""
        from app.services.avito_client import AvitoClient

        await global_cache.clear()
        try:
            account = _make_account(id=9)
            db = AsyncMock()
            client = AvitoClient(account, db)
            client._request_with_retry = AsyncMock(
                return_value=_make_response({"fees": [], "meta": {"pages": 1}})
            )
            client._headers = AsyncMock(return_value={})

            with patch("app.cache.cache.set", new=AsyncMock()) as mock_set:
                await client.get_report_fees(report_id=3)
                _, kwargs = mock_set.call_args
                assert kwargs["ttl_seconds"] == 5 * 60
        finally:
            await global_cache.clear()

    @pytest.mark.asyncio
    async def test_cache_key_isolates_accounts(self):
        """Same report_id on different accounts → independent cache entries."""
        from app.services.avito_client import AvitoClient

        await global_cache.clear()
        try:
            db = AsyncMock()

            acc1 = _make_account(id=1)
            client1 = AvitoClient(acc1, db)
            client1._request_with_retry = AsyncMock(
                return_value=_make_response({"fees": [{"a": 1}], "meta": {"pages": 1}})
            )
            client1._headers = AsyncMock(return_value={})

            acc2 = _make_account(id=2)
            client2 = AvitoClient(acc2, db)
            client2._request_with_retry = AsyncMock(
                return_value=_make_response({"fees": [{"b": 2}], "meta": {"pages": 1}})
            )
            client2._headers = AsyncMock(return_value={})

            r1 = await client1.get_report_fees(report_id=100, report_status="completed")
            r2 = await client2.get_report_fees(report_id=100, report_status="completed")

            assert r1["fees"] == [{"a": 1}]
            assert r2["fees"] == [{"b": 2}]
            # Both made one API call — neither served the other's cached entry
            assert client1._request_with_retry.call_count == 1
            assert client2._request_with_retry.call_count == 1
        finally:
            await global_cache.clear()

    @pytest.mark.asyncio
    async def test_failure_is_not_cached(self):
        """When the API call raises and no fees collected, no cache entry written."""
        from app.services.avito_client import AvitoClient

        await global_cache.clear()
        try:
            account = _make_account(id=99)
            db = AsyncMock()
            client = AvitoClient(account, db)
            client._request_with_retry = AsyncMock(side_effect=httpx.RequestError("boom"))
            client._headers = AsyncMock(return_value={})

            r = await client.get_report_fees(report_id=500, report_status="completed")
            assert r == {"fees": [], "total": 0, "report_id": 500}
            # Cache should be empty so a retry would hit the API again
            assert await global_cache.get("report_fees:99:500") is None
        finally:
            await global_cache.clear()

    @pytest.mark.asyncio
    async def test_custom_paging_skips_cache(self):
        """Non-canonical (page!=0 or per_page!=100) calls don't read or write cache."""
        from app.services.avito_client import AvitoClient

        await global_cache.clear()
        try:
            account = _make_account(id=11)
            db = AsyncMock()
            client = AvitoClient(account, db)
            client._request_with_retry = AsyncMock(
                return_value=_make_response({"fees": [], "meta": {"pages": 1}})
            )
            client._headers = AsyncMock(return_value={})

            with patch("app.cache.cache.set", new=AsyncMock()) as mock_set:
                with patch("app.cache.cache.get", new=AsyncMock(return_value=None)) as mock_get:
                    await client.get_report_fees(report_id=7, page=2, per_page=50)
                    mock_set.assert_not_called()
                    mock_get.assert_not_called()
        finally:
            await global_cache.clear()
