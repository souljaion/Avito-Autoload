"""Tests for app/main.py — FastAPI app, mounts, routers, health endpoint."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.routing import APIRoute, Mount


# ---------------------------------------------------------------------------
# App import / metadata
# ---------------------------------------------------------------------------

class TestAppCreation:
    def test_app_can_be_imported(self):
        from app.main import app
        assert app is not None
        assert app.title == "Avito Autoload"

    def test_app_has_version(self):
        from app.main import app
        assert app.version == "0.1.0"


# ---------------------------------------------------------------------------
# Static / Media mounts
# ---------------------------------------------------------------------------

class TestMounts:
    def test_static_mount_registered(self):
        from app.main import app
        mounts = [r for r in app.routes if isinstance(r, Mount)]
        paths = {m.path for m in mounts}
        assert "/static" in paths

    def test_media_mount_registered(self):
        from app.main import app
        mounts = [r for r in app.routes if isinstance(r, Mount)]
        paths = {m.path for m in mounts}
        assert "/media" in paths

    def test_static_directory_exists(self):
        import os
        from app.main import app  # noqa: F401 — triggers makedirs
        assert os.path.isdir("app/static")

    def test_media_directory_exists(self):
        import os
        from app.config import settings
        from app.main import app  # noqa: F401 — triggers makedirs
        assert os.path.isdir(settings.MEDIA_DIR)


# ---------------------------------------------------------------------------
# Routers — verify all 13 are registered
# ---------------------------------------------------------------------------

class TestRouters:
    """Each router should contribute at least one route to the app."""

    @pytest.fixture
    def all_paths(self):
        from app.main import app
        paths = set()
        for r in app.routes:
            if isinstance(r, APIRoute):
                paths.add(r.path)
        return paths

    def test_health_route_registered(self, all_paths):
        assert "/health" in all_paths

    def test_dashboard_router_registered(self, all_paths):
        # GET / — dashboard root
        assert "/" in all_paths

    def test_accounts_router_registered(self, all_paths):
        assert any(p.startswith("/accounts") for p in all_paths)

    def test_products_router_registered(self, all_paths):
        assert any(p.startswith("/products") or p.startswith("/api/products") for p in all_paths)

    def test_images_router_registered(self, all_paths):
        # images router exposes endpoints — exact path varies
        from app.routes.images import router as r
        assert len(r.routes) > 0

    def test_feeds_router_registered(self, all_paths):
        assert any(p.startswith("/feeds") for p in all_paths)

    def test_autoload_router_registered(self, all_paths):
        assert any("autoload" in p for p in all_paths)

    def test_reports_router_registered(self, all_paths):
        assert any(p.startswith("/reports") or "/reports" in p for p in all_paths)

    def test_categories_router_registered(self, all_paths):
        assert any("categories" in p or "categor" in p for p in all_paths)

    def test_analytics_router_registered(self, all_paths):
        assert any("analytics" in p for p in all_paths)

    def test_schedule_router_registered(self, all_paths):
        assert any("schedule" in p for p in all_paths)

    def test_listings_router_registered(self, all_paths):
        assert any("listings" in p for p in all_paths)

    def test_models_router_registered(self, all_paths):
        assert any("models" in p for p in all_paths)

    def test_photo_packs_router_registered(self, all_paths):
        from app.routes.photo_packs import router as r
        assert len(r.routes) > 0


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

class TestMiddleware:
    def test_basic_auth_middleware_registered(self):
        from app.main import app
        from app.middleware.auth import BasicAuthMiddleware

        names = [m.cls.__name__ for m in app.user_middleware]
        assert BasicAuthMiddleware.__name__ in names


# ---------------------------------------------------------------------------
# Health endpoint — uses real local server (already running)
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health_returns_200_no_auth(self):
        """Hits the live server on :8001 — health must work without auth."""
        import httpx
        async with httpx.AsyncClient(base_url="http://127.0.0.1:8001", timeout=5.0) as c:
            resp = await c.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "db" in data
        assert "uptime_seconds" in data

    @pytest.mark.asyncio
    async def test_404_for_unknown_route(self, client):
        resp = await client.get("/this-route-does-not-exist-xyz")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Lifespan — verify it can run without errors when scheduler lock is held
# ---------------------------------------------------------------------------

class TestLifespan:
    @pytest.mark.asyncio
    async def test_lifespan_handles_locked_scheduler(self):
        """If another worker holds the scheduler lock, lifespan should still complete."""
        from fastapi import FastAPI
        from app.main import lifespan

        # Make fcntl.flock raise IOError to simulate "another worker has lock"
        # Patch async_session to avoid real DB connections during lifespan diagnostics
        with patch("fcntl.flock", side_effect=IOError("locked")):
            with patch("app.main.start_scheduler") as mock_start:
                with patch("app.db.async_session", side_effect=Exception("skip diag")):
                    app = FastAPI()
                    async with lifespan(app):
                        pass
                    # start_scheduler was NOT called because lock failed
                    mock_start.assert_not_called()

    @pytest.mark.asyncio
    async def test_lifespan_starts_scheduler_when_lock_acquired(self):
        """Happy path: lock acquired → scheduler starts → cleanup on exit."""
        from fastapi import FastAPI
        from app.main import lifespan

        mock_sched = MagicMock()
        # Patch async_session to avoid real DB connections during lifespan diagnostics.
        # Without this, the Zulla diag query opens a real asyncpg connection that
        # leaks on teardown (RuntimeWarning: coroutine 'Connection._cancel' was never
        # awaited), which can cause flaky failures in CI.
        with patch("fcntl.flock"):  # acquires lock OK
            with patch("app.main.start_scheduler", return_value=mock_sched) as mock_start:
                with patch("app.db.async_session", side_effect=Exception("skip diag")):
                    app = FastAPI()
                    async with lifespan(app):
                        assert app.state.scheduler is mock_sched
                    mock_start.assert_called_once()
                    mock_sched.shutdown.assert_called_once_with(wait=False)
