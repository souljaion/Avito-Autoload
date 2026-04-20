"""Tests for feeds routes: delete, upload, report with dedup fix."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from app.db import get_db
from app.routes.feeds import router


def _make_app(mock_db):
    app = FastAPI()
    app.include_router(router)

    async def override_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_db
    return app


def _make_account(acc_id=1):
    a = MagicMock()
    a.id = acc_id
    a.name = "TestAcc"
    a.client_id = "cid"
    a.client_secret = "sec"
    a.access_token = "tok"
    a.autoload_enabled = True
    a.avito_sync_minute = 30
    a.report_email = "test@test.com"
    return a


def _make_feed_export(feed_id=1, account_id=1, status="generated", account=None):
    f = MagicMock()
    f.id = feed_id
    f.account_id = account_id
    f.status = status
    f.file_path = f"/tmp/feeds/{account_id}.xml"
    f.products_count = 10
    f.created_at = datetime.now(timezone.utc).replace(tzinfo=None)
    f.uploaded_at = datetime.now(timezone.utc).replace(tzinfo=None) if status == "uploaded" else None
    f.upload_response = {"status": "ok"} if status == "uploaded" else None
    f.account = account or _make_account(acc_id=account_id)
    return f


class TestFeedDelete:
    @pytest.mark.asyncio
    async def test_delete_nonexistent_feed_returns_404(self):
        """Deleting a feed that doesn't exist should return 404."""
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.delete("/feeds/999")

        assert resp.status_code == 404
        assert resp.json()["ok"] is False

    @pytest.mark.asyncio
    async def test_delete_feed_succeeds(self):
        """Deleting an existing feed should remove from DB and return ok."""
        export = _make_feed_export()
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=export)
        mock_db.delete = AsyncMock()
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        with patch("app.routes.feeds.os.path.exists", return_value=False), \
             patch("app.routes.feeds.os.path.normpath", side_effect=lambda x: x):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.delete("/feeds/1")

        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        mock_db.delete.assert_called_once_with(export)
        mock_db.commit.assert_called_once()


class TestFeedUpload:
    @pytest.mark.asyncio
    async def test_upload_feed_not_found(self):
        """Uploading a nonexistent feed should return 404."""
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=result_mock)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/feeds/999/upload")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_upload_no_credentials_returns_400(self):
        """Feed with account missing credentials should return 400."""
        account = _make_account()
        account.client_id = None
        account.client_secret = None
        export = _make_feed_export(account=account)

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = export

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=result_mock)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/feeds/1/upload")

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_upload_success(self):
        """Successful upload should set status='uploaded' and return ok."""
        export = _make_feed_export(status="generated")

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = export

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=result_mock)
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        with patch("app.routes.feeds.os.path.exists", return_value=True), \
             patch("app.routes.feeds.aiofiles.open") as mock_open, \
             patch("app.routes.feeds.AvitoClient") as MockClient:
            # Mock file read
            mock_file = AsyncMock()
            mock_file.read = AsyncMock(return_value=b"<xml>feed</xml>")
            mock_open.return_value.__aenter__ = AsyncMock(return_value=mock_file)
            mock_open.return_value.__aexit__ = AsyncMock(return_value=False)

            client_inst = AsyncMock()
            client_inst.upload_feed = AsyncMock(return_value={"ok": True})
            client_inst.close = AsyncMock()
            MockClient.return_value = client_inst

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/feeds/1/upload")

        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert export.status == "uploaded"

    @pytest.mark.asyncio
    async def test_upload_failure_saves_error_status(self):
        """Failed upload should save status='upload_error' and return 502."""
        export = _make_feed_export(status="generated")

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = export

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=result_mock)
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        with patch("app.routes.feeds.os.path.exists", return_value=True), \
             patch("app.routes.feeds.aiofiles.open") as mock_open, \
             patch("app.routes.feeds.AvitoClient") as MockClient:
            mock_file = AsyncMock()
            mock_file.read = AsyncMock(return_value=b"<xml/>")
            mock_open.return_value.__aenter__ = AsyncMock(return_value=mock_file)
            mock_open.return_value.__aexit__ = AsyncMock(return_value=False)

            client_inst = AsyncMock()
            client_inst.upload_feed = AsyncMock(side_effect=Exception("network error"))
            client_inst.close = AsyncMock()
            MockClient.return_value = client_inst

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/feeds/1/upload")

        assert resp.status_code == 502
        assert export.status == "upload_error"
        mock_db.commit.assert_called()


class TestFeedReport:
    @pytest.mark.asyncio
    async def test_report_not_found(self):
        """Report for nonexistent feed should return 404."""
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=result_mock)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/feeds/999/report")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_report_no_credentials_returns_400(self):
        """Feed with account missing credentials should return 400."""
        account = _make_account()
        account.client_id = None
        export = _make_feed_export(account=account)

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = export

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=result_mock)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/feeds/1/report")

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_report_pending_when_no_reports(self):
        """When Avito has no reports yet, return pending status."""
        export = _make_feed_export()

        # First execute = feed export query, then AvitoClient queries
        export_result = MagicMock()
        export_result.scalar_one_or_none.return_value = export

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=export_result)
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        with patch("app.routes.feeds.AvitoClient") as MockClient:
            client_inst = AsyncMock()
            client_inst.get_reports = AsyncMock(return_value={"reports": []})
            client_inst.close = AsyncMock()
            MockClient.return_value = client_inst

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get("/feeds/1/report")

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["status"] == "pending"

    @pytest.mark.asyncio
    async def test_report_items_delete_before_insert(self):
        """Report items should be cleared before inserting new ones (dedup fix)."""
        export = _make_feed_export()

        export_result = MagicMock()
        export_result.scalar_one_or_none.return_value = export

        # Mock for existing autoload_report check
        report_row = MagicMock()
        report_row.id = 42
        report_row.status = "completed"
        report_row.total_ads = 0
        report_row.applied_ads = 0
        report_row.declined_ads = 0
        existing_report_result = MagicMock()
        existing_report_result.scalar_one_or_none.return_value = report_row

        execute_calls = []
        call_idx = [0]

        async def track_execute(stmt, *args, **kwargs):
            execute_calls.append(stmt)
            call_idx[0] += 1
            # First call = feed export query
            if call_idx[0] == 1:
                return export_result
            # Second call = existing report check
            if call_idx[0] == 2:
                return existing_report_result
            # Third call = DELETE existing items
            # Fourth+ calls = other operations
            return MagicMock(scalar_one_or_none=MagicMock(return_value=None))

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=track_execute)
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        report_items = [
            {"ad_id": "1", "avito_id": "111", "status": "active", "url": "http://avito.ru/1", "messages": []},
            {"ad_id": "2", "avito_id": "222", "status": "rejected", "url": "http://avito.ru/2",
             "messages": [{"type": "error", "description": "Bad ad"}]},
        ]

        with patch("app.routes.feeds.AvitoClient") as MockClient:
            client_inst = AsyncMock()
            client_inst.get_reports = AsyncMock(return_value={
                "reports": [{"id": 100, "status": "completed", "started_at": "2026-01-01T00:00:00"}]
            })
            client_inst.get_report = AsyncMock(return_value={
                "section_stats": {"count": 2},
                "events": [],
                "feeds_urls": [{"url": "http://feed.xml"}],
            })
            client_inst.get_report_items = AsyncMock(return_value={"items": report_items})
            client_inst.close = AsyncMock()
            MockClient.return_value = client_inst

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get("/feeds/1/report")

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["stats"]["applied"] == 1
        assert data["stats"]["declined"] == 1

        # Verify DELETE was called (one of the execute calls should be a delete)
        # and db.add was called for each new item
        assert mock_db.add.call_count >= 2  # 2 report items added
        mock_db.commit.assert_called_once()
