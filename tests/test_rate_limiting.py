"""Tests for slowapi rate limiting on /api/analytics/fees and /products/{id}/avito-status."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from slowapi.errors import RateLimitExceeded

from app.db import get_db
from app.rate_limit import limiter, rate_limit_exceeded_handler


def _build_app(routers):
    """Build a fresh FastAPI app with the limiter wired and given routers."""
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
    for r in routers:
        app.include_router(r)
    return app


def _override_db(app, mock_db):
    async def _gen():
        yield mock_db
    app.dependency_overrides[get_db] = _gen


@pytest.fixture(autouse=True)
def reset_limiter_between_tests():
    """Each test gets a clean rate limiter window."""
    limiter.reset()
    yield
    limiter.reset()


# ---------------------------------------------------------------------------
# /api/analytics/fees — 10 / minute
# ---------------------------------------------------------------------------

class TestFeesRateLimit:
    @pytest.mark.asyncio
    async def test_first_10_requests_pass(self):
        from app.routes.analytics import router

        # Mock DB returns 404 for any account_id (cheaper than full mock)
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)

        app = _build_app([router])
        _override_db(app, mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            for i in range(10):
                resp = await c.get("/api/analytics/fees?account_id=1")
                assert resp.status_code != 429, f"request #{i+1} should not be rate-limited"

    @pytest.mark.asyncio
    async def test_11th_request_is_429(self):
        from app.routes.analytics import router

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)

        app = _build_app([router])
        _override_db(app, mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            for _ in range(10):
                await c.get("/api/analytics/fees?account_id=1")
            resp = await c.get("/api/analytics/fees?account_id=1")

        assert resp.status_code == 429
        body = resp.json()
        assert body["error"] == "rate limit exceeded"
        assert "Превышен лимит" in body["detail"]
        assert "10" in body["detail"]


# ---------------------------------------------------------------------------
# /products/{id}/avito-status — 30 / minute
# ---------------------------------------------------------------------------

class TestAvitoStatusRateLimit:
    @pytest.mark.asyncio
    async def test_first_30_requests_pass(self):
        from app.routes.products import router

        # Make DB return None for product → 404 quickly without hitting Avito
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        app = _build_app([router])
        _override_db(app, mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            for i in range(30):
                resp = await c.get("/products/999/avito-status")
                assert resp.status_code != 429, f"request #{i+1} should not be rate-limited"

    @pytest.mark.asyncio
    async def test_31st_request_is_429(self):
        from app.routes.products import router

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        app = _build_app([router])
        _override_db(app, mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            for _ in range(30):
                await c.get("/products/999/avito-status")
            resp = await c.get("/products/999/avito-status")

        assert resp.status_code == 429
        body = resp.json()
        assert body["error"] == "rate limit exceeded"
        assert "30" in body["detail"]


# ---------------------------------------------------------------------------
# Limit isolation — fees and avito-status have independent buckets
# ---------------------------------------------------------------------------

class TestLimitIsolation:
    @pytest.mark.asyncio
    async def test_separate_endpoints_have_separate_buckets(self):
        from app.routes.analytics import router as analytics_router
        from app.routes.products import router as products_router

        # Mock for analytics
        mock_db_a = AsyncMock()
        mock_db_a.get = AsyncMock(return_value=None)
        # Mock for products
        result_p = MagicMock()
        result_p.scalar_one_or_none.return_value = None
        mock_db_p = AsyncMock()
        mock_db_p.execute = AsyncMock(return_value=result_p)

        # Build separate apps so each gets its own DB override
        app_a = _build_app([analytics_router])
        _override_db(app_a, mock_db_a)
        app_p = _build_app([products_router])
        _override_db(app_p, mock_db_p)

        # Exhaust /api/analytics/fees (10/min)
        async with AsyncClient(transport=ASGITransport(app=app_a), base_url="http://test") as c:
            for _ in range(10):
                await c.get("/api/analytics/fees?account_id=1")
            blocked = await c.get("/api/analytics/fees?account_id=1")
            assert blocked.status_code == 429

        # /products/.../avito-status should still work
        async with AsyncClient(transport=ASGITransport(app=app_p), base_url="http://test") as c:
            r = await c.get("/products/1/avito-status")
            assert r.status_code != 429
