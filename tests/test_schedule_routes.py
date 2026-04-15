"""Tests for schedule routes."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from app.db import get_db
from app.routes.schedule import router


def _make_app(mock_db):
    app = FastAPI()
    app.include_router(router)

    async def override_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_db
    return app


def _empty_db():
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_result.scalars.return_value.unique.return_value.all.return_value = []
    mock_result.scalar.return_value = None
    mock_result.scalar_one_or_none.return_value = None
    mock_result.all.return_value = []
    # For metrics query (.one())
    mock_one = MagicMock()
    mock_one.active_count = 0
    mock_one.scheduled_today = 0
    mock_one.published_today = 0
    mock_one.draft_count = 0
    mock_result.one.return_value = mock_one

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.get = AsyncMock(return_value=None)
    return mock_db


def _make_account(id=1, name="Test", sync_minute=None):
    acc = MagicMock()
    acc.id = id
    acc.name = name
    acc.avito_sync_minute = sync_minute
    return acc


def _make_product(id=1, status="scheduled", account_id=1, title="Nike Air",
                  price=5000, scheduled_at=None):
    p = MagicMock()
    p.id = id
    p.status = status
    p.account_id = account_id
    p.title = title
    p.price = price
    p.scheduled_at = scheduled_at or (datetime.utcnow() + timedelta(hours=1))
    p.published_at = None
    p.images = []
    p.account = _make_account(id=account_id)
    return p


class TestScheduleOverview:
    @pytest.mark.asyncio
    async def test_empty_overview(self):
        """Empty DB returns empty accounts list."""
        mock_db = _empty_db()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/schedule/overview")

        assert resp.status_code == 200
        data = resp.json()
        assert "accounts" in data
        assert data["accounts"] == []

    @pytest.mark.asyncio
    async def test_overview_with_accounts(self):
        """Overview returns account cards with counts."""
        acc = _make_account(id=1, name="Zulla", sync_minute=15)

        call_count = [0]
        def make_result_for_call(*args, **kwargs):
            call_count[0] += 1
            r = MagicMock()
            if call_count[0] == 1:  # accounts query
                r.scalars.return_value.all.return_value = [acc]
            elif call_count[0] == 2:  # counts query
                row = MagicMock()
                row.account_id = 1
                row.active = 5
                row.scheduled = 2
                row.draft = 3
                row.scheduled_today = 1
                row.published_today = 0
                r.all.return_value = [row]
            elif call_count[0] == 3:  # hourly_load query
                r.all.return_value = []
            elif call_count[0] == 4:  # upcoming query
                r.scalars.return_value.all.return_value = []
            return r

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=make_result_for_call)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/schedule/overview")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["accounts"]) == 1
        assert data["accounts"][0]["name"] == "Zulla"
        assert data["accounts"][0]["sync_minute"] == 15
        assert "totals" in data
        assert "hourly_load" in data


class TestScheduleAccountData:
    @pytest.mark.asyncio
    async def test_scheduled_products_for_account(self):
        """Returns scheduled products, metrics, and recommendations."""
        mock_db = _empty_db()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/schedule/1")

        assert resp.status_code == 200
        data = resp.json()
        assert "scheduled" in data
        assert "metrics" in data
        assert "hourly_load" in data
        assert "drafts" in data
        assert "active" in data
        assert "recommendations" in data
        assert isinstance(data["scheduled"], list)
        assert isinstance(data["recommendations"], list)
        assert len(data["hourly_load"]) == 24


class TestCancelScheduled:
    @pytest.mark.asyncio
    async def test_cancel_not_found(self):
        """Cancel returns 404 for non-existent product."""
        mock_db = _empty_db()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/schedule/9999/cancel")

        assert resp.status_code == 404
        data = resp.json()
        assert data["ok"] is False

    @pytest.mark.asyncio
    async def test_cancel_wrong_status(self):
        """Cancel returns 400 if product is not scheduled."""
        product = _make_product(id=1, status="active")
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=product)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/schedule/1/cancel")

        assert resp.status_code == 400
        assert resp.json()["ok"] is False

    @pytest.mark.asyncio
    async def test_cancel_success(self):
        """Cancel sets product to draft and clears scheduled_at."""
        product = _make_product(id=1, status="scheduled")
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=product)
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/schedule/1/cancel")

        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert product.status == "draft"
        assert product.scheduled_at is None
        assert product.scheduled_account_id is None
        mock_db.commit.assert_awaited_once()


class TestScheduleAccountPage:
    @pytest.mark.asyncio
    async def test_account_not_found(self):
        """Returns 404 for non-existent account."""
        mock_db = _empty_db()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/schedule/9999")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_account_found_returns_html(self):
        """Returns HTML page when account exists."""
        acc = _make_account(id=5, name="TestAcc")
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=acc)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/schedule/5")

        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]


class TestSchedulePage:
    @pytest.mark.asyncio
    async def test_schedule_page_returns_html(self):
        """GET /schedule returns HTML with accounts list."""
        acc = _make_account(id=1, name="TestShop")
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [acc]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/schedule")

        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]


class TestOverviewUpcoming:
    @pytest.mark.asyncio
    async def test_overview_with_upcoming_products(self):
        """Overview includes upcoming scheduled products per account."""
        acc = _make_account(id=1, name="Shop1", sync_minute=30)
        sched_time = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
        product = _make_product(id=10, status="scheduled", account_id=1,
                                title="Nike Air Max 90 Super Long Title That Exceeds Limit",
                                scheduled_at=sched_time)

        call_count = [0]
        def make_result(*args, **kwargs):
            call_count[0] += 1
            r = MagicMock()
            if call_count[0] == 1:  # accounts
                r.scalars.return_value.all.return_value = [acc]
            elif call_count[0] == 2:  # counts
                row = MagicMock()
                row.account_id = 1
                row.active = 3
                row.scheduled = 1
                row.draft = 0
                row.scheduled_today = 1
                row.published_today = 0
                r.all.return_value = [row]
            elif call_count[0] == 3:  # hourly_load
                r.all.return_value = []
            elif call_count[0] == 4:  # upcoming
                r.scalars.return_value.all.return_value = [product]
            return r

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=make_result)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/schedule/overview")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["accounts"]) == 1
        acc_data = data["accounts"][0]
        assert acc_data["active"] == 3
        assert acc_data["scheduled"] == 1
        assert len(acc_data["upcoming"]) == 1
        # Title should be truncated at 35 chars + "..."
        assert acc_data["upcoming"][0]["title"].endswith("...")
        assert acc_data["upcoming"][0]["scheduled_at"] is not None


def _make_account_data_db(scheduled_products=None, draft_products=None,
                          active_products=None, models=None):
    """Create a mock DB for per-account data endpoint.

    Handles the many queries in the new endpoint by returning
    sensible defaults for each call pattern.
    """
    scheduled_products = scheduled_products or []
    draft_products = draft_products or []
    active_products = active_products or []
    models = models or []

    def make_result(*args, **kwargs):
        r = MagicMock()
        # Default empty results for all access patterns
        r.scalars.return_value.all.return_value = []
        r.scalars.return_value.unique.return_value.all.return_value = []
        r.all.return_value = []
        r.scalar.return_value = None
        # For metrics .one()
        mock_one = MagicMock()
        mock_one.active_count = len(active_products)
        mock_one.scheduled_today = len(scheduled_products)
        mock_one.published_today = 0
        mock_one.draft_count = len(draft_products)
        r.one.return_value = mock_one
        return r

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=make_result)
    return mock_db


class TestScheduleAccountDataWithProducts:
    @pytest.mark.asyncio
    async def test_returns_basic_structure(self):
        """Per-account endpoint returns all expected fields."""
        mock_db = _empty_db()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/schedule/1")

        assert resp.status_code == 200
        data = resp.json()
        assert "scheduled" in data
        assert "drafts" in data
        assert "active" in data
        assert "metrics" in data
        assert "hourly_load" in data
        assert "recommendations" in data
        assert len(data["hourly_load"]) == 24
        assert data["metrics"]["active_count"] == 0
        assert data["metrics"]["draft_count"] == 0

    @pytest.mark.asyncio
    async def test_metrics_structure(self):
        """Metrics include all expected fields."""
        mock_db = _empty_db()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/schedule/1")

        assert resp.status_code == 200
        metrics = resp.json()["metrics"]
        assert "active_count" in metrics
        assert "scheduled_today" in metrics
        assert "published_today" in metrics
        assert "draft_count" in metrics
        assert "dead_count" in metrics


class TestOverviewStructure:
    """Tests for the enhanced overview endpoint structure."""

    @pytest.mark.asyncio
    async def test_overview_returns_totals_and_hourly(self):
        """Overview response contains totals, hourly_load, and accounts."""
        acc = _make_account(id=1, name="TestShop", sync_minute=20)

        call_count = [0]
        def make_result(*args, **kwargs):
            call_count[0] += 1
            r = MagicMock()
            if call_count[0] == 1:  # accounts
                r.scalars.return_value.all.return_value = [acc]
            elif call_count[0] == 2:  # counts
                row = MagicMock()
                row.account_id = 1
                row.active = 10
                row.scheduled = 3
                row.draft = 5
                row.scheduled_today = 2
                row.published_today = 1
                r.all.return_value = [row]
            elif call_count[0] == 3:  # hourly_load
                r.all.return_value = []
            elif call_count[0] == 4:  # upcoming
                r.scalars.return_value.all.return_value = []
            else:
                r.scalars.return_value.all.return_value = []
                r.all.return_value = []
            return r

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=make_result)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/schedule/overview")

        assert resp.status_code == 200
        data = resp.json()

        # Structure checks
        assert "totals" in data
        assert "hourly_load" in data
        assert "accounts" in data

        # Totals
        totals = data["totals"]
        assert totals["scheduled_today"] == 2
        assert totals["published_today"] == 1
        assert totals["drafts"] == 5

        # Hourly load is exactly 24 elements
        assert len(data["hourly_load"]) == 24
        assert all(isinstance(v, int) for v in data["hourly_load"])

        # Account card has new fields
        acc_data = data["accounts"][0]
        assert acc_data["scheduled_today"] == 2
        assert acc_data["published_today"] == 1
        assert acc_data["draft"] == 5
        assert acc_data["feed_time"] == "XX:20"


class TestPerAccountMetrics:
    """Tests for per-account endpoint metrics and hourly_load."""

    @pytest.mark.asyncio
    async def test_account_metrics_correct(self):
        """Per-account endpoint returns correct metric values from DB."""
        mock_db = _empty_db()
        # Override the .one() to return specific values
        metrics_one = MagicMock()
        metrics_one.active_count = 15
        metrics_one.scheduled_today = 3
        metrics_one.published_today = 2
        metrics_one.draft_count = 7

        original_execute = mock_db.execute

        call_count = [0]
        def custom_execute(*args, **kwargs):
            call_count[0] += 1
            r = MagicMock()
            r.scalars.return_value.all.return_value = []
            r.scalars.return_value.unique.return_value.all.return_value = []
            r.all.return_value = []
            r.scalar.return_value = None
            if call_count[0] == 1:  # metrics query
                r.one.return_value = metrics_one
            else:
                mock_one = MagicMock()
                mock_one.active_count = 0
                mock_one.scheduled_today = 0
                mock_one.published_today = 0
                mock_one.draft_count = 0
                r.one.return_value = mock_one
            return r

        mock_db.execute = AsyncMock(side_effect=custom_execute)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/schedule/1")

        assert resp.status_code == 200
        metrics = resp.json()["metrics"]
        assert metrics["active_count"] == 15
        assert metrics["scheduled_today"] == 3
        assert metrics["published_today"] == 2
        assert metrics["draft_count"] == 7
        assert metrics["dead_count"] == 0  # no active products with avito_id

    @pytest.mark.asyncio
    async def test_hourly_load_24_elements(self):
        """hourly_load always has exactly 24 elements."""
        mock_db = _empty_db()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/schedule/1")

        assert resp.status_code == 200
        hourly = resp.json()["hourly_load"]
        assert len(hourly) == 24
        assert all(isinstance(v, int) for v in hourly)
        assert all(v >= 0 for v in hourly)
