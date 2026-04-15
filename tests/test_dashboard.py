"""Tests for dashboard endpoints: command_center and dashboard_data."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from app.db import get_db
from app.routes.dashboard import router


def _make_app(mock_db):
    """Create a test FastAPI app with mocked DB dependency."""
    app = FastAPI()
    app.include_router(router)

    async def override_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_db
    return app


def _empty_db():
    """Create a mock DB that returns empty results for all queries."""
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_result.scalars.return_value.unique.return_value.all.return_value = []
    mock_result.scalar.return_value = None
    mock_result.scalar_one_or_none.return_value = None
    mock_result.all.return_value = []

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.get = AsyncMock(return_value=None)
    return mock_db


class TestCommandCenter:
    @pytest.mark.asyncio
    async def test_empty_database_returns_valid_structure(self):
        """Empty DB should return valid JSON with all required keys."""
        mock_db = _empty_db()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/dashboard/command-center")

        assert resp.status_code == 200
        data = resp.json()
        assert "attention" in data
        assert "scheduled_today" in data
        assert "stats" in data
        assert "recommendations" in data
        assert isinstance(data["attention"], list)
        assert isinstance(data["scheduled_today"], list)
        assert isinstance(data["stats"], dict)
        assert isinstance(data["recommendations"], list)

    @pytest.mark.asyncio
    async def test_stats_keys_present(self):
        """Stats block should contain all expected metric keys."""
        mock_db = _empty_db()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/dashboard/command-center")

        stats = resp.json()["stats"]
        expected_keys = {"active_ads", "active_accounts", "total_accounts",
                         "total_models", "dead_ads", "weak_ads", "problem_ads",
                         "last_sync", "sync_stale"}
        assert expected_keys.issubset(stats.keys())

    @pytest.mark.asyncio
    async def test_empty_attention_on_empty_db(self):
        """No models or products → no attention items."""
        mock_db = _empty_db()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/dashboard/command-center")

        data = resp.json()
        assert data["attention"] == []
        assert data["stats"]["active_ads"] == 0
        assert data["stats"]["dead_ads"] == 0


class TestDashboardData:
    @pytest.mark.asyncio
    async def test_empty_database_returns_valid_structure(self):
        """Empty DB should return valid JSON with all keys."""
        mock_db = _empty_db()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/dashboard")

        assert resp.status_code == 200
        data = resp.json()
        assert "products" in data
        assert "accounts" in data
        assert "latest_products" in data
        assert data["products"]["total"] == 0
        assert data["products"]["active"] == 0

    @pytest.mark.asyncio
    async def test_returns_empty_lists_not_null(self):
        """All list fields should be empty lists, not null."""
        mock_db = _empty_db()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/dashboard")

        data = resp.json()
        assert isinstance(data["accounts"], list)
        assert isinstance(data["latest_products"], list)
        assert isinstance(data["reports"], list)
        assert isinstance(data["scheduled"], list)
        assert isinstance(data["problem_products"], list)


def _make_account(id=1, name="Test", sync_minute=None, feed_token="abc-123"):
    acc = MagicMock()
    acc.id = id
    acc.name = name
    acc.avito_sync_minute = sync_minute
    acc.feed_token = feed_token
    return acc


def _make_product(id=1, status="active", account_id=1, title="Nike Air",
                  price=5000, description="desc", category="Обувь",
                  subcategory="Кроссовки", goods_type="type", goods_subtype="subtype",
                  avito_id=None, scheduled_at=None):
    p = MagicMock()
    p.id = id
    p.status = status
    p.account_id = account_id
    p.title = title
    p.price = price
    p.description = description
    p.category = category
    p.subcategory = subcategory
    p.goods_type = goods_type
    p.goods_subtype = goods_subtype
    p.avito_id = avito_id
    p.scheduled_at = scheduled_at
    p.created_at = datetime(2026, 4, 15, 10, 0, 0)
    p.images = []
    acc = _make_account(id=account_id)
    p.account = acc
    return p


def _make_model(id=1, name="Air Max", brand="Nike", products=None, photo_packs=None):
    m = MagicMock()
    m.id = id
    m.name = name
    m.brand = brand
    m.products = products or []
    m.photo_packs = photo_packs or []
    return m


class TestCommandCenterWithData:
    @pytest.mark.asyncio
    async def test_model_no_ads_attention(self):
        """Model with no active/published/scheduled products triggers attention."""
        model = _make_model(id=1, name="Air Max", brand="Nike", products=[])

        call_count = [0]
        def make_result(*args, **kwargs):
            call_count[0] += 1
            r = MagicMock()
            if call_count[0] == 1:  # models query
                r.scalars.return_value.unique.return_value.all.return_value = [model]
            elif call_count[0] == 2:  # declined ads
                r.scalars.return_value.all.return_value = []
            elif call_count[0] == 3:  # dead ads window stats
                r.all.return_value = []
            elif call_count[0] == 4:  # baseline stats
                r.all.return_value = []
            elif call_count[0] == 5:  # dead products
                r.scalars.return_value.all.return_value = []
            elif call_count[0] == 6:  # scheduled today
                r.scalars.return_value.all.return_value = []
            elif call_count[0] == 7:  # active count
                r.scalar.return_value = 0
            elif call_count[0] == 8:  # active accounts
                r.scalar.return_value = 0
            elif call_count[0] == 9:  # total accounts
                r.scalar.return_value = 0
            elif call_count[0] == 10:  # last sync
                r.scalar.return_value = None
            elif call_count[0] == 11:  # accounts for recommendations
                r.scalars.return_value.all.return_value = []
            return r

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=make_result)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/dashboard/command-center")

        data = resp.json()
        assert len(data["attention"]) >= 1
        assert data["attention"][0]["type"] == "model_no_ads"
        assert data["attention"][0]["title"] == "Nike — Air Max"

    @pytest.mark.asyncio
    async def test_scheduled_today_with_sync_minute(self):
        """Scheduled products display time based on account sync_minute."""
        now = datetime.utcnow()
        today_10am = now.replace(hour=10, minute=0, second=0, microsecond=0)
        product = _make_product(
            id=1, status="scheduled", scheduled_at=today_10am, title="Test Shoe"
        )
        product.account.avito_sync_minute = 15

        call_count = [0]
        def make_result(*args, **kwargs):
            call_count[0] += 1
            r = MagicMock()
            if call_count[0] == 1:  # models
                r.scalars.return_value.unique.return_value.all.return_value = []
            elif call_count[0] == 2:  # declined
                r.scalars.return_value.all.return_value = []
            elif call_count[0] == 3:  # window stats
                r.all.return_value = []
            elif call_count[0] == 4:  # baseline
                r.all.return_value = []
            elif call_count[0] == 5:  # dead products
                r.scalars.return_value.all.return_value = []
            elif call_count[0] == 6:  # scheduled today
                r.scalars.return_value.all.return_value = [product]
            elif call_count[0] == 7:  # active count
                r.scalar.return_value = 0
            elif call_count[0] == 8:  # active accounts
                r.scalar.return_value = 0
            elif call_count[0] == 9:  # total accounts
                r.scalar.return_value = 0
            elif call_count[0] == 10:  # last sync
                r.scalar.return_value = None
            elif call_count[0] == 11:  # accounts for recommendations
                r.scalars.return_value.all.return_value = []
            return r

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=make_result)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/dashboard/command-center")

        data = resp.json()
        assert len(data["scheduled_today"]) == 1
        assert data["scheduled_today"][0]["title"] == "Test Shoe"
        # display_time should use sync_minute format "~HH:MM"
        assert data["scheduled_today"][0]["display_time"].startswith("~")

    @pytest.mark.asyncio
    async def test_recommendations_add_model(self):
        """Recommendation to add model to missing account."""
        acc1 = _make_account(id=1, name="Shop1")
        acc2 = _make_account(id=2, name="Shop2")

        # Model has product on acc1 but not acc2
        mp = MagicMock()
        mp.account_id = 1
        mp.status = "active"
        model = _make_model(id=3, name="Yeezy 350", brand="Adidas", products=[mp])

        call_count = [0]
        def make_result(*args, **kwargs):
            call_count[0] += 1
            r = MagicMock()
            if call_count[0] == 1:  # models
                r.scalars.return_value.unique.return_value.all.return_value = [model]
            elif call_count[0] == 2:  # declined
                r.scalars.return_value.all.return_value = []
            elif call_count[0] == 3:  # window stats
                r.all.return_value = []
            elif call_count[0] == 4:  # baseline
                r.all.return_value = []
            elif call_count[0] == 5:  # dead products
                r.scalars.return_value.all.return_value = []
            elif call_count[0] == 6:  # scheduled today
                r.scalars.return_value.all.return_value = []
            elif call_count[0] == 7:  # active count
                r.scalar.return_value = 1
            elif call_count[0] == 8:  # active accounts
                r.scalar.return_value = 1
            elif call_count[0] == 9:  # total accounts
                r.scalar.return_value = 2
            elif call_count[0] == 10:  # last sync
                r.scalar.return_value = None
            elif call_count[0] == 11:  # accounts for recommendations
                r.scalars.return_value.all.return_value = [acc1, acc2]
            return r

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=make_result)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/dashboard/command-center")

        data = resp.json()
        recs = [r for r in data["recommendations"] if r["type"] == "add_model"]
        assert len(recs) >= 1
        assert recs[0]["model_id"] == 3
        assert "Shop2" in recs[0]["message"]

    @pytest.mark.asyncio
    async def test_no_scheduled_recommendation(self):
        """When no products scheduled today, a recommendation is added."""
        mock_db = _empty_db()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/dashboard/command-center")

        data = resp.json()
        no_sched = [r for r in data["recommendations"] if r["type"] == "no_scheduled"]
        assert len(no_sched) == 1

    @pytest.mark.asyncio
    async def test_sync_stale_flag(self):
        """sync_stale is True when last sync was more than 4 hours ago."""
        stale_time = datetime.utcnow() - timedelta(hours=5)

        call_count = [0]
        def make_result(*args, **kwargs):
            call_count[0] += 1
            r = MagicMock()
            if call_count[0] == 1:  # models
                r.scalars.return_value.unique.return_value.all.return_value = []
            elif call_count[0] == 2:  # declined
                r.scalars.return_value.all.return_value = []
            elif call_count[0] == 3:  # window stats
                r.all.return_value = []
            elif call_count[0] == 4:  # baseline
                r.all.return_value = []
            elif call_count[0] == 5:  # dead products
                r.scalars.return_value.all.return_value = []
            elif call_count[0] == 6:  # scheduled today
                r.scalars.return_value.all.return_value = []
            elif call_count[0] == 7:  # active count
                r.scalar.return_value = 0
            elif call_count[0] == 8:  # active accounts
                r.scalar.return_value = 0
            elif call_count[0] == 9:  # total accounts
                r.scalar.return_value = 0
            elif call_count[0] == 10:  # last sync - stale
                r.scalar.return_value = stale_time
            elif call_count[0] == 11:  # accounts
                r.scalars.return_value.all.return_value = []
            return r

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=make_result)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/dashboard/command-center")

        data = resp.json()
        assert data["stats"]["sync_stale"] is True
        assert data["stats"]["last_sync"] is not None


class TestDashboardDataWithProducts:
    @pytest.mark.asyncio
    async def test_problem_products_missing_description(self):
        """Products without description appear in problem_products."""
        product = _make_product(id=1, status="active", description=None)
        product.images = []

        call_count = [0]
        def make_result(*args, **kwargs):
            call_count[0] += 1
            r = MagicMock()
            if call_count[0] == 1:  # status counts
                row = MagicMock()
                row.__getitem__ = lambda self, i: ("active", 1)[i]
                r.all.return_value = [("active", 1)]
            elif call_count[0] == 2:  # problem candidates
                r.scalars.return_value.all.return_value = [product]
            elif call_count[0] == 3:  # latest products
                r.scalars.return_value.all.return_value = [product]
            elif call_count[0] == 4:  # accounts
                r.scalars.return_value.all.return_value = []
            elif call_count[0] == 5:  # latest gen feed
                r.scalars.return_value.all.return_value = []
            elif call_count[0] == 6:  # latest upload feed
                r.scalars.return_value.all.return_value = []
            elif call_count[0] == 7:  # last upload overall
                r.scalar_one_or_none.return_value = None
            elif call_count[0] == 8:  # reports
                r.scalars.return_value.all.return_value = []
            elif call_count[0] == 9:  # scheduled products
                r.scalars.return_value.all.return_value = []
            return r

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=make_result)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/dashboard")

        data = resp.json()
        assert len(data["problem_products"]) >= 1
        problems = data["problem_products"][0]["problems"]
        assert "нет описания" in problems
        assert "нет фото" in problems

    @pytest.mark.asyncio
    async def test_dashboard_page_returns_html(self):
        """GET / returns dashboard HTML page."""
        mock_db = _empty_db()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/")

        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
