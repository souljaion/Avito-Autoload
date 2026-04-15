"""Tests for autoload_sync: sync applied ads from Avito reports into products."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from app.db import get_db
from app.routes.autoload import router
from app.services.autoload_sync import sync_ads_from_avito


# ── Helpers ──

def _make_account(id=1, name="TestAcc", client_id="cid", client_secret="sec"):
    acc = MagicMock()
    acc.id = id
    acc.name = name
    acc.client_id = client_id
    acc.client_secret = client_secret
    acc.autoload_enabled = True
    return acc


def _make_report_item(ad_id, avito_id, status="applied"):
    return {"ad_id": ad_id, "avito_id": avito_id, "status": status, "url": f"https://avito.ru/{avito_id}"}


def _make_app(mock_db):
    app = FastAPI()
    app.include_router(router)

    async def override_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_db
    return app


# ── Unit tests for sync_ads_from_avito ──

class TestSyncAdsFromAvito:
    @pytest.mark.asyncio
    async def test_creates_new_product_when_not_in_db(self):
        """Applied item with new avito_id creates a product."""
        account = _make_account()

        # Mock DB
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=account)

        # existing_by_avito_id: empty
        r1_scalars = MagicMock()
        r1_scalars.all.return_value = []
        r1 = MagicMock()
        r1.scalars.return_value = r1_scalars

        # existing_by_sku: empty
        r2_scalars = MagicMock()
        r2_scalars.all.return_value = []
        r2 = MagicMock()
        r2.scalars.return_value = r2_scalars

        # all_avito_ids: empty
        r3 = MagicMock()
        r3.all.return_value = []

        mock_db.execute = AsyncMock(side_effect=[r1, r2, r3])
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()

        # Mock client
        mock_client = AsyncMock()
        mock_client.get_reports = AsyncMock(return_value={
            "reports": [{"id": 100}]
        })
        mock_client.get_report_items_all = AsyncMock(return_value=[
            _make_report_item("ad_1", 12345),
        ])
        mock_client.close = AsyncMock()

        result = await sync_ads_from_avito(1, mock_db, client=mock_client)

        assert result["created"] == 1
        assert result["synced"] == 0
        assert result["skipped"] == 0
        assert result["error"] is None
        mock_db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_updates_existing_product_avito_id(self):
        """Product matched by sku/ad_id gets avito_id filled in."""
        account = _make_account()

        existing_product = MagicMock()
        existing_product.avito_id = None
        existing_product.sku = "ad_1"
        existing_product.account_id = 1

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=account)

        # existing_by_avito_id: empty
        r1_scalars = MagicMock()
        r1_scalars.all.return_value = []
        r1 = MagicMock()
        r1.scalars.return_value = r1_scalars

        # existing_by_sku: one product
        r2_scalars = MagicMock()
        r2_scalars.all.return_value = [existing_product]
        r2 = MagicMock()
        r2.scalars.return_value = r2_scalars

        # all_avito_ids: empty
        r3 = MagicMock()
        r3.all.return_value = []

        mock_db.execute = AsyncMock(side_effect=[r1, r2, r3])
        mock_db.commit = AsyncMock()

        mock_client = AsyncMock()
        mock_client.get_reports = AsyncMock(return_value={"reports": [{"id": 100}]})
        mock_client.get_report_items_all = AsyncMock(return_value=[
            _make_report_item("ad_1", 99999),
        ])

        result = await sync_ads_from_avito(1, mock_db, client=mock_client)

        assert result["synced"] == 1
        assert result["created"] == 0
        assert existing_product.avito_id == 99999

    @pytest.mark.asyncio
    async def test_skips_non_applied_status(self):
        """Items with status != 'applied' are skipped."""
        account = _make_account()

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=account)

        r1_scalars = MagicMock()
        r1_scalars.all.return_value = []
        r1 = MagicMock()
        r1.scalars.return_value = r1_scalars

        r2_scalars = MagicMock()
        r2_scalars.all.return_value = []
        r2 = MagicMock()
        r2.scalars.return_value = r2_scalars

        r3 = MagicMock()
        r3.all.return_value = []

        mock_db.execute = AsyncMock(side_effect=[r1, r2, r3])
        mock_db.commit = AsyncMock()

        mock_client = AsyncMock()
        mock_client.get_reports = AsyncMock(return_value={"reports": [{"id": 100}]})
        mock_client.get_report_items_all = AsyncMock(return_value=[
            _make_report_item("ad_1", 111, status="declined"),
            _make_report_item("ad_2", 222, status="processing"),
            _make_report_item("ad_3", 333, status="applied"),
        ])

        result = await sync_ads_from_avito(1, mock_db, client=mock_client)

        assert result["skipped"] == 2
        assert result["created"] == 1

    @pytest.mark.asyncio
    async def test_pagination_merges_multiple_pages(self):
        """Items from multiple pages should all be processed."""
        account = _make_account()

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=account)

        r1_scalars = MagicMock()
        r1_scalars.all.return_value = []
        r1 = MagicMock()
        r1.scalars.return_value = r1_scalars

        r2_scalars = MagicMock()
        r2_scalars.all.return_value = []
        r2 = MagicMock()
        r2.scalars.return_value = r2_scalars

        r3 = MagicMock()
        r3.all.return_value = []

        mock_db.execute = AsyncMock(side_effect=[r1, r2, r3])
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()

        # Return 3 items — all from get_report_items_all (pagination is internal)
        mock_client = AsyncMock()
        mock_client.get_reports = AsyncMock(return_value={"reports": [{"id": 100}]})
        mock_client.get_report_items_all = AsyncMock(return_value=[
            _make_report_item("ad_1", 111),
            _make_report_item("ad_2", 222),
            _make_report_item("ad_3", 333),
        ])

        result = await sync_ads_from_avito(1, mock_db, client=mock_client)

        assert result["created"] == 3
        assert mock_db.add.call_count == 3

    @pytest.mark.asyncio
    async def test_api_error_does_not_crash(self):
        """API error should be caught and returned in result."""
        account = _make_account()

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=account)
        mock_db.rollback = AsyncMock()

        mock_client = AsyncMock()
        mock_client.get_reports = AsyncMock(side_effect=Exception("Connection timeout"))
        mock_client.close = AsyncMock()

        result = await sync_ads_from_avito(1, mock_db, client=mock_client)

        assert result["error"] is not None
        assert "Connection timeout" in result["error"]
        assert result["created"] == 0

    @pytest.mark.asyncio
    async def test_no_reports_returns_error(self):
        """Empty reports list should return error, not crash."""
        account = _make_account()

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=account)

        mock_client = AsyncMock()
        mock_client.get_reports = AsyncMock(return_value={"reports": []})

        result = await sync_ads_from_avito(1, mock_db, client=mock_client)

        assert result["error"] == "No reports found"
        assert result["created"] == 0

    @pytest.mark.asyncio
    async def test_skips_duplicate_avito_id_across_accounts(self):
        """If avito_id already exists on another account, skip it."""
        account = _make_account()

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=account)

        r1_scalars = MagicMock()
        r1_scalars.all.return_value = []
        r1 = MagicMock()
        r1.scalars.return_value = r1_scalars

        r2_scalars = MagicMock()
        r2_scalars.all.return_value = []
        r2 = MagicMock()
        r2.scalars.return_value = r2_scalars

        # avito_id 12345 already exists on another account
        r3 = MagicMock()
        r3.all.return_value = [(12345,)]

        mock_db.execute = AsyncMock(side_effect=[r1, r2, r3])
        mock_db.commit = AsyncMock()

        mock_client = AsyncMock()
        mock_client.get_reports = AsyncMock(return_value={"reports": [{"id": 100}]})
        mock_client.get_report_items_all = AsyncMock(return_value=[
            _make_report_item("ad_1", 12345),
        ])

        result = await sync_ads_from_avito(1, mock_db, client=mock_client)

        assert result["skipped"] == 1
        assert result["created"] == 0

    @pytest.mark.asyncio
    async def test_existing_by_avito_id_counted_as_synced(self):
        """Product already matched by avito_id is counted as synced, not created."""
        account = _make_account()

        existing = MagicMock()
        existing.avito_id = 12345
        existing.account_id = 1

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=account)

        r1_scalars = MagicMock()
        r1_scalars.all.return_value = [existing]
        r1 = MagicMock()
        r1.scalars.return_value = r1_scalars

        r2_scalars = MagicMock()
        r2_scalars.all.return_value = []
        r2 = MagicMock()
        r2.scalars.return_value = r2_scalars

        r3 = MagicMock()
        r3.all.return_value = [(12345,)]

        mock_db.execute = AsyncMock(side_effect=[r1, r2, r3])
        mock_db.commit = AsyncMock()

        mock_client = AsyncMock()
        mock_client.get_reports = AsyncMock(return_value={"reports": [{"id": 100}]})
        mock_client.get_report_items_all = AsyncMock(return_value=[
            _make_report_item("ad_1", 12345),
        ])

        result = await sync_ads_from_avito(1, mock_db, client=mock_client)

        assert result["synced"] == 1
        assert result["created"] == 0


# ── Route tests ──

class TestSyncAdsEndpoint:
    @pytest.mark.asyncio
    async def test_account_not_found(self):
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/accounts/999/autoload/sync-ads")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_no_credentials(self):
        acc = _make_account(client_id=None, client_secret=None)
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=acc)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/accounts/1/autoload/sync-ads")

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_success(self):
        acc = _make_account()
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=acc)
        app = _make_app(mock_db)

        with patch("app.routes.autoload.sync_ads_from_avito", new_callable=AsyncMock) as mock_sync:
            mock_sync.return_value = {"created": 5, "synced": 3, "skipped": 2, "error": None}

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/accounts/1/autoload/sync-ads")

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["created"] == 5
        assert data["synced"] == 3
        assert data["skipped"] == 2

    @pytest.mark.asyncio
    async def test_sync_error_returns_502(self):
        acc = _make_account()
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=acc)
        app = _make_app(mock_db)

        with patch("app.routes.autoload.sync_ads_from_avito", new_callable=AsyncMock) as mock_sync:
            mock_sync.return_value = {"created": 0, "synced": 0, "skipped": 0, "error": "API timeout"}

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/accounts/1/autoload/sync-ads")

        assert resp.status_code == 502
        assert resp.json()["error"] == "API timeout"
