"""Tests for analytics: efficiency markers and fees."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from app.db import get_db
from app.routes.analytics import router


def _make_app(mock_db):
    app = FastAPI()
    app.include_router(router)

    async def override_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_db
    return app


def _make_efficiency_db(products_data):
    """Build a mock DB for the /api/analytics/efficiency endpoint.

    products_data: list of dicts with keys:
      id, avito_id, title, price, status, account_id, account_name,
      views_baseline (before 3d window), views_latest (in window),
      extra (optional)

    The efficiency endpoint makes these queries in order:
      1. window_stmt: MAX/MIN views + count in 3-day window, grouped by product_id
      2. baseline_stmt: MAX views before 3-day window, grouped by product_id
      3. totals_stmt: MAX views/contacts all-time, grouped by product_id
      4. today_stmt: MAX views/contacts today, grouped by product_id
      5. yesterday_stmt: MAX views/contacts yesterday, grouped by product_id
      6. products query: active products with avito_id
      7. last_sync: MAX(captured_at)
    """
    # Build per-product mock results
    window_rows = []
    baseline_rows = []
    totals_rows = []

    for p in products_data:
        pid = p["id"]
        vb = p.get("views_baseline")
        vl = p.get("views_latest", 0)
        snapshots = p.get("snapshots", 2)  # number of snapshots in window

        if snapshots >= 1:
            window_rows.append(MagicMock(
                product_id=pid,
                max_views=vl,
                min_views=vb if vb is not None and snapshots >= 2 else vl,
                cnt=snapshots,
            ))

        if vb is not None:
            baseline_rows.append(MagicMock(
                product_id=pid,
                baseline_views=vb,
            ))

        totals_rows.append(MagicMock(
            product_id=pid,
            views_total=vl,
            contacts_total=0,
        ))

    # Build product mocks
    product_mocks = []
    for p in products_data:
        pm = MagicMock()
        pm.id = p["id"]
        pm.avito_id = p.get("avito_id", p["id"] * 100)
        pm.title = p.get("title", f"Product {p['id']}")
        pm.price = p.get("price", 1000)
        pm.status = p.get("status", "active")
        pm.account_id = p.get("account_id", 1)
        acc_mock = MagicMock()
        acc_mock.name = p.get("account_name", "TestAcc")
        pm.account = acc_mock
        pm.image_url = None
        pm.images = [MagicMock(url="http://img.jpg", is_main=True, sort_order=0)]
        pm.brand = p.get("brand", "Nike")
        pm.goods_type = p.get("goods_type", "Мужская обувь")
        pm.extra = p.get("extra") or {}
        pm.published_at = None
        product_mocks.append(pm)

    # Result 1: window query
    r1 = MagicMock()
    r1.all.return_value = window_rows

    # Result 2: baseline query
    r2 = MagicMock()
    r2.all.return_value = baseline_rows

    # Result 3: totals query
    r3 = MagicMock()
    r3.all.return_value = totals_rows

    # Result 4: today query (empty)
    r4 = MagicMock()
    r4.all.return_value = []

    # Result 5: yesterday query (empty)
    r5 = MagicMock()
    r5.all.return_value = []

    # Result 6: products query
    r6_scalars = MagicMock()
    r6_scalars.all.return_value = product_mocks
    r6 = MagicMock()
    r6.scalars.return_value = r6_scalars

    # Result 7: last_sync
    r7 = MagicMock()
    r7.scalar.return_value = datetime.utcnow()

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=[r1, r2, r3, r4, r5, r6, r7])
    return mock_db


class TestEfficiencyMarkers:
    @pytest.mark.asyncio
    async def test_dead_marker_zero_views_delta(self):
        """Product with 0 views delta over 3 days → dead marker."""
        db = _make_efficiency_db([{
            "id": 1, "views_baseline": 100, "views_latest": 100,
        }])
        app = _make_app(db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/analytics/efficiency")

        assert resp.status_code == 200
        products = resp.json()["products"]
        assert len(products) == 1
        assert products[0]["marker"] == "dead"

    @pytest.mark.asyncio
    async def test_alive_marker_good_views(self):
        """Product with 50 views delta over 3 days → alive marker."""
        db = _make_efficiency_db([{
            "id": 1, "views_baseline": 0, "views_latest": 50,
        }])
        app = _make_app(db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/analytics/efficiency")

        products = resp.json()["products"]
        assert products[0]["marker"] == "alive"

    @pytest.mark.asyncio
    async def test_weak_marker_low_views(self):
        """Product with 5 views delta over 3 days → weak marker (< 10)."""
        db = _make_efficiency_db([{
            "id": 1, "views_baseline": 100, "views_latest": 105,
        }])
        app = _make_app(db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/analytics/efficiency")

        products = resp.json()["products"]
        assert products[0]["marker"] == "weak"

    @pytest.mark.asyncio
    async def test_unknown_marker_single_snapshot(self):
        """Product with only 1 snapshot (no baseline) → unknown marker."""
        db = _make_efficiency_db([{
            "id": 1, "views_baseline": None, "views_latest": 50,
            "snapshots": 1,
        }])
        app = _make_app(db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/analytics/efficiency")

        products = resp.json()["products"]
        assert products[0]["marker"] == "unknown"

    @pytest.mark.asyncio
    async def test_summary_counts_match_markers(self):
        """Summary counts should match actual marker distribution."""
        db = _make_efficiency_db([
            {"id": 1, "views_baseline": 100, "views_latest": 100},  # dead
            {"id": 2, "views_baseline": 100, "views_latest": 100},  # dead
            {"id": 3, "views_baseline": 0, "views_latest": 50},     # alive
            {"id": 4, "views_baseline": None, "views_latest": 10, "snapshots": 1},  # unknown
        ])
        app = _make_app(db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/analytics/efficiency")

        summary = resp.json()["summary"]
        assert summary["dead"] == 2
        assert summary["alive"] == 1
        assert summary["unknown"] == 1

    @pytest.mark.asyncio
    async def test_avito_messages_included_in_response(self):
        """Products with avito_messages in extra should include them."""
        db = _make_efficiency_db([{
            "id": 1, "views_baseline": 0, "views_latest": 50,
            "extra": {"avito_messages": [{"title": "Blocked", "description": "Rules violation"}]},
        }])
        app = _make_app(db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/analytics/efficiency")

        products = resp.json()["products"]
        assert products[0]["avito_messages"] is not None
        assert products[0]["avito_messages"][0]["title"] == "Blocked"


class TestGetReportFees:
    """Tests for AvitoClient.get_report_fees method."""

    @pytest.mark.asyncio
    async def test_get_report_fees_happy_path(self):
        """Single page of fees returns correct structure."""
        from app.services.avito_client import AvitoClient

        mock_account = MagicMock()
        mock_account.access_token = "test_token"
        mock_account.token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        mock_account.client_id = "test_id"
        mock_account.client_secret = "test_secret"

        mock_db = AsyncMock()

        client = AvitoClient(mock_account, mock_db)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "fees": [
                {"ad_id": "1", "avito_id": 100, "amount_total": 50, "type": "placement"},
                {"ad_id": "2", "avito_id": 200, "amount_total": 30, "type": "vas"},
            ],
            "meta": {"pages": 1},
        }
        mock_response.raise_for_status = MagicMock()

        client._client = AsyncMock()
        client._client.request = AsyncMock(return_value=mock_response)

        result = await client.get_report_fees(123)

        assert result["report_id"] == 123
        assert result["total"] == 2
        assert len(result["fees"]) == 2
        assert result["fees"][0]["amount_total"] == 50

        await client.close()

    @pytest.mark.asyncio
    async def test_get_report_fees_pagination(self):
        """Two pages of fees are merged correctly."""
        from app.services.avito_client import AvitoClient

        mock_account = MagicMock()
        mock_account.access_token = "test_token"
        mock_account.token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        mock_db = AsyncMock()
        client = AvitoClient(mock_account, mock_db)

        page1_resp = MagicMock()
        page1_resp.status_code = 200
        page1_resp.json.return_value = {
            "fees": [{"ad_id": "1", "amount_total": 50}],
            "meta": {"pages": 2},
        }
        page1_resp.raise_for_status = MagicMock()

        page2_resp = MagicMock()
        page2_resp.status_code = 200
        page2_resp.json.return_value = {
            "fees": [{"ad_id": "2", "amount_total": 30}],
            "meta": {"pages": 2},
        }
        page2_resp.raise_for_status = MagicMock()

        client._client = AsyncMock()
        client._client.request = AsyncMock(side_effect=[page1_resp, page2_resp])

        result = await client.get_report_fees(456)

        assert result["total"] == 2
        assert len(result["fees"]) == 2
        assert result["fees"][0]["ad_id"] == "1"
        assert result["fees"][1]["ad_id"] == "2"

        await client.close()


class TestFeesEndpoint:
    @pytest.mark.asyncio
    async def test_fees_endpoint_returns_total(self):
        """GET /api/analytics/fees returns correct total_fees_rub."""
        mock_account = MagicMock()
        mock_account.id = 1
        mock_account.name = "TestAccount"
        mock_account.access_token = "token"
        mock_account.token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        mock_account.client_id = "cid"
        mock_account.client_secret = "csec"

        mock_report = MagicMock()
        mock_report.avito_report_id = "999"

        mock_db = AsyncMock()

        # db.get(Account, 1) returns mock_account
        mock_db.get = AsyncMock(return_value=mock_account)

        # db.execute for AutoloadReport query
        report_scalars = MagicMock()
        report_scalars.first.return_value = mock_report
        report_result = MagicMock()
        report_result.scalars.return_value = report_scalars
        mock_db.execute = AsyncMock(return_value=report_result)

        app = _make_app(mock_db)

        fees_response = {
            "fees": [
                {"ad_id": "1", "avito_id": 100, "amount_total": 50, "type": "placement"},
                {"ad_id": "2", "avito_id": 200, "amount_total": 75, "type": "vas"},
            ],
            "total": 2,
            "report_id": 999,
        }

        with patch("app.services.avito_client.AvitoClient") as MockClient:
            instance = AsyncMock()
            instance.get_report_fees = AsyncMock(return_value=fees_response)
            instance.close = AsyncMock()
            MockClient.return_value = instance

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get("/api/analytics/fees?account_id=1")

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["total_fees_rub"] == 125
        assert data["report_id"] == 999
        assert len(data["fees"]) == 2


# ── Tests for GET /api/analytics ──


def _make_item_stat(product_id, views, contacts, favorites, captured_at):
    s = MagicMock()
    s.product_id = product_id
    s.views = views
    s.contacts = contacts
    s.favorites = favorites
    s.captured_at = captured_at
    return s


def _make_analytics_product(
    pid, avito_id, title, price, status, account_name,
    image_url=None, images=None, listings=None,
):
    p = MagicMock()
    p.id = pid
    p.avito_id = avito_id
    p.title = title
    p.price = price
    p.status = status
    acc = MagicMock()
    acc.name = account_name
    p.account = acc
    p.image_url = image_url
    p.images = images or []
    p.listings = listings or []
    return p


def _build_analytics_db(stats_list, products_list, last_sync_dt):
    """Build a mock AsyncSession for /api/analytics.

    The endpoint makes 3 queries:
      1. select(ItemStats) order by product_id, captured_at desc -> all_stats
      2. select(Product) with options, where avito_id is not None -> products
      3. select(func.max(ItemStats.captured_at)) -> last_sync scalar
    """
    # Result 1: all_stats
    r1_scalars = MagicMock()
    r1_scalars.all.return_value = stats_list
    r1 = MagicMock()
    r1.scalars.return_value = r1_scalars

    # Result 2: products
    r2_scalars = MagicMock()
    r2_scalars.all.return_value = products_list
    r2 = MagicMock()
    r2.scalars.return_value = r2_scalars

    # Result 3: last_sync
    r3 = MagicMock()
    r3.scalar.return_value = last_sync_dt

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=[r1, r2, r3])
    return mock_db


class TestAnalyticsData:
    @pytest.mark.asyncio
    async def test_empty_products(self):
        """No products with avito_id should return empty items."""
        db = _build_analytics_db([], [], None)
        app = _make_app(db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/analytics")

        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["last_sync"] is None

    @pytest.mark.asyncio
    async def test_single_product_no_stats(self):
        """Product with no stats should have 0 views/contacts/favorites."""
        product = _make_analytics_product(
            pid=1, avito_id=100, title="Sneakers", price=5000,
            status="active", account_name="Shop1",
        )
        db = _build_analytics_db([], [product], None)
        app = _make_app(db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/analytics")

        data = resp.json()
        assert len(data["items"]) == 1
        item = data["items"][0]
        assert item["views"] == 0
        assert item["contacts"] == 0
        assert item["favorites"] == 0
        assert item["conversion"] == 0
        assert item["trend_dir"] is None
        assert item["views_today"] is None

    @pytest.mark.asyncio
    async def test_product_with_stats_and_trend(self):
        """Product with 2 stats snapshots should compute trend."""
        now = datetime.now(timezone.utc)
        stats = [
            _make_item_stat(1, views=150, contacts=10, favorites=5, captured_at=now),
            _make_item_stat(1, views=100, contacts=8, favorites=3, captured_at=now - timedelta(days=1)),
        ]
        product = _make_analytics_product(
            pid=1, avito_id=100, title="Sneakers", price=5000,
            status="active", account_name="Shop1",
        )
        db = _build_analytics_db(stats, [product], now)
        app = _make_app(db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/analytics")

        item = resp.json()["items"][0]
        assert item["views"] == 150
        assert item["contacts"] == 10
        assert item["favorites"] == 5
        assert item["trend_dir"] == "up"
        assert item["trend_delta"] == 50

    @pytest.mark.asyncio
    async def test_conversion_calculation(self):
        """Conversion should be contacts/views * 100 rounded to 1 decimal."""
        now = datetime.now(timezone.utc)
        stats = [
            _make_item_stat(1, views=200, contacts=15, favorites=0, captured_at=now),
        ]
        product = _make_analytics_product(
            pid=1, avito_id=100, title="Sneakers", price=5000,
            status="active", account_name="Shop1",
        )
        db = _build_analytics_db(stats, [product], now)
        app = _make_app(db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/analytics")

        item = resp.json()["items"][0]
        assert item["conversion"] == 7.5  # 15/200*100

    @pytest.mark.asyncio
    async def test_trend_down(self):
        """Views decreasing should show trend_dir=down."""
        now = datetime.now(timezone.utc)
        stats = [
            _make_item_stat(1, views=50, contacts=2, favorites=1, captured_at=now),
            _make_item_stat(1, views=100, contacts=5, favorites=3, captured_at=now - timedelta(days=1)),
        ]
        product = _make_analytics_product(
            pid=1, avito_id=100, title="Sneakers", price=5000,
            status="active", account_name="Shop1",
        )
        db = _build_analytics_db(stats, [product], now)
        app = _make_app(db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/analytics")

        item = resp.json()["items"][0]
        assert item["trend_dir"] == "down"
        assert item["trend_delta"] == -50

    @pytest.mark.asyncio
    async def test_views_today_computed(self):
        """views_today should be latest(today) - previous(yesterday)."""
        today = datetime.now(timezone.utc)
        yesterday = today - timedelta(days=1)
        stats = [
            _make_item_stat(1, views=200, contacts=10, favorites=5, captured_at=today),
            _make_item_stat(1, views=150, contacts=8, favorites=3, captured_at=yesterday),
        ]
        product = _make_analytics_product(
            pid=1, avito_id=100, title="Sneakers", price=5000,
            status="active", account_name="Shop1",
        )
        db = _build_analytics_db(stats, [product], today)
        app = _make_app(db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/analytics")

        item = resp.json()["items"][0]
        assert item["views_today"] == 50

    @pytest.mark.asyncio
    async def test_photos_synced_count(self):
        """photos_synced should count items with resolved images."""
        now = datetime.now(timezone.utc)
        p1 = _make_analytics_product(
            pid=1, avito_id=100, title="A", price=1000,
            status="active", account_name="S1", image_url="/img/a.jpg",
        )
        p2 = _make_analytics_product(
            pid=2, avito_id=200, title="B", price=2000,
            status="active", account_name="S1", image_url=None,
        )
        db = _build_analytics_db([], [p1, p2], now)
        app = _make_app(db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/analytics")

        data = resp.json()
        assert data["photos_synced"] == 1
        assert data["photos_total"] == 2

    @pytest.mark.asyncio
    async def test_last_sync_formatted(self):
        """last_sync should be formatted as dd.mm.YYYY HH:MM."""
        sync_dt = datetime(2026, 4, 15, 14, 30, 0)
        db = _build_analytics_db([], [], sync_dt)
        app = _make_app(db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/analytics")

        assert resp.json()["last_sync"] == "15.04.2026 14:30"
