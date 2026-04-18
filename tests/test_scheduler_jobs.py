"""Tests for scheduler.py: job functions, _run_with_retry, health tracking."""

from datetime import datetime
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.scheduler import (
    _run_with_retry,
    _job_sync_stats,
    _job_publish_scheduled,
    _job_sync_images,
    _job_check_sold,
    _job_import_items,
    _job_cleanup_removed,
    _job_cleanup_old_feeds,
    _job_refresh_tokens,
    _record_job_success,
    _job_last_success,
    get_job_health,
    RETRY_DELAY,
    MAX_RETRIES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_async_session(mock_db):
    """Return async context manager that yields mock_db."""
    @asynccontextmanager
    async def _ctx():
        yield mock_db
    return _ctx


# ---------------------------------------------------------------------------
# _record_job_success / get_job_health
# ---------------------------------------------------------------------------

class TestJobHealth:
    def test_record_and_get(self):
        _job_last_success.clear()
        _record_job_success("test_job")
        health = get_job_health()
        assert "test_job" in health
        # ISO string format
        datetime.fromisoformat(health["test_job"])

    def test_get_empty(self):
        _job_last_success.clear()
        assert get_job_health() == {}


# ---------------------------------------------------------------------------
# _run_with_retry
# ---------------------------------------------------------------------------

class TestRunWithRetry:
    @pytest.mark.asyncio
    async def test_success_first_try(self):
        mock_db = AsyncMock()
        coro_factory = AsyncMock(return_value="ok")

        with patch("app.scheduler.async_session", _fake_async_session(mock_db)):
            result = await _run_with_retry("test", coro_factory)
        assert result == "ok"
        coro_factory.assert_called_once_with(mock_db)

    @pytest.mark.asyncio
    async def test_returns_true_when_coro_returns_none(self):
        mock_db = AsyncMock()
        coro_factory = AsyncMock(return_value=None)

        with patch("app.scheduler.async_session", _fake_async_session(mock_db)):
            result = await _run_with_retry("test", coro_factory)
        assert result is True

    @pytest.mark.asyncio
    async def test_retries_on_failure(self):
        mock_db = AsyncMock()
        coro_factory = AsyncMock(side_effect=[Exception("boom"), "recovered"])

        with patch("app.scheduler.async_session", _fake_async_session(mock_db)):
            with patch("app.scheduler.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                result = await _run_with_retry("test", coro_factory)
        assert result == "recovered"
        mock_sleep.assert_called_once_with(RETRY_DELAY)

    @pytest.mark.asyncio
    async def test_exhausted_retries_returns_false(self):
        mock_db = AsyncMock()
        coro_factory = AsyncMock(side_effect=Exception("always fails"))

        with patch("app.scheduler.async_session", _fake_async_session(mock_db)):
            with patch("app.scheduler.asyncio.sleep", new_callable=AsyncMock):
                result = await _run_with_retry("test", coro_factory)
        assert result is False
        assert coro_factory.call_count == MAX_RETRIES


# ---------------------------------------------------------------------------
# _job_sync_stats
# ---------------------------------------------------------------------------

class TestJobSyncStats:
    @pytest.mark.asyncio
    async def test_success_logs_results(self):
        mock_db = AsyncMock()
        stats_results = [
            {"account": "Acc1", "synced": 5, "total": 10},
            {"account": "Acc2", "error": "timeout"},
        ]
        _job_last_success.pop("stats_sync", None)

        with patch("app.scheduler.async_session", _fake_async_session(mock_db)):
            with patch("app.scheduler.sync_all_stats", new_callable=AsyncMock, return_value=stats_results):
                await _job_sync_stats()

        assert "stats_sync" in _job_last_success

    @pytest.mark.asyncio
    async def test_failure_no_success_recorded(self):
        mock_db = AsyncMock()
        _job_last_success.pop("stats_sync", None)

        with patch("app.scheduler.async_session", _fake_async_session(mock_db)):
            with patch("app.scheduler.sync_all_stats", new_callable=AsyncMock, side_effect=Exception("fail")):
                with patch("app.scheduler.asyncio.sleep", new_callable=AsyncMock):
                    await _job_sync_stats()

        assert "stats_sync" not in _job_last_success


# ---------------------------------------------------------------------------
# _job_publish_scheduled
# ---------------------------------------------------------------------------

class TestJobPublishScheduled:
    @pytest.mark.asyncio
    async def test_success_with_published(self):
        mock_db = AsyncMock()
        publish_result = {"published": 2, "skipped": 1, "errors": 0}
        _job_last_success.pop("publish_scheduled", None)

        with patch("app.scheduler.async_session", _fake_async_session(mock_db)):
            with patch("app.scheduler.publish_scheduled_products", new_callable=AsyncMock, return_value=publish_result):
                await _job_publish_scheduled()

        assert "publish_scheduled" in _job_last_success

    @pytest.mark.asyncio
    async def test_noop_when_nothing_published(self):
        mock_db = AsyncMock()
        publish_result = {"published": 0, "skipped": 5, "errors": 0}
        _job_last_success.pop("publish_scheduled", None)

        with patch("app.scheduler.async_session", _fake_async_session(mock_db)):
            with patch("app.scheduler.publish_scheduled_products", new_callable=AsyncMock, return_value=publish_result):
                await _job_publish_scheduled()

        assert "publish_scheduled" in _job_last_success


# ---------------------------------------------------------------------------
# _job_sync_images
# ---------------------------------------------------------------------------

class TestJobSyncImages:
    @pytest.mark.asyncio
    async def test_success(self):
        mock_db = AsyncMock()
        sync_result = {"synced": 3, "already_had": 7}
        _job_last_success.pop("image_sync", None)

        with patch("app.scheduler.async_session", _fake_async_session(mock_db)):
            with patch("app.scheduler.sync_images_from_crm", new_callable=AsyncMock, return_value=sync_result):
                await _job_sync_images()

        assert "image_sync" in _job_last_success


# ---------------------------------------------------------------------------
# _job_check_sold
# ---------------------------------------------------------------------------

class TestJobCheckSold:
    @pytest.mark.asyncio
    async def test_success_with_sold(self):
        mock_db = AsyncMock()
        results = [{"account_name": "Acc1", "marked_sold": 2}]
        _job_last_success.pop("sold_detection", None)

        with patch("app.scheduler.async_session", _fake_async_session(mock_db)):
            with patch("app.scheduler.check_all_accounts_sold", new_callable=AsyncMock, return_value=results):
                await _job_check_sold()

        assert "sold_detection" in _job_last_success

    @pytest.mark.asyncio
    async def test_success_no_sold(self):
        mock_db = AsyncMock()
        results = [{"account_name": "Acc1", "marked_sold": 0}]
        _job_last_success.pop("sold_detection", None)

        with patch("app.scheduler.async_session", _fake_async_session(mock_db)):
            with patch("app.scheduler.check_all_accounts_sold", new_callable=AsyncMock, return_value=results):
                await _job_check_sold()

        assert "sold_detection" in _job_last_success


# ---------------------------------------------------------------------------
# _job_import_items
# ---------------------------------------------------------------------------

class TestJobImportItems:
    @pytest.mark.asyncio
    async def test_success(self):
        mock_db = AsyncMock()
        results = [
            {"account": "Acc1", "imported": 3, "total": 10, "marked_sold": 1},
        ]
        _job_last_success.pop("avito_import", None)

        with patch("app.scheduler.async_session", _fake_async_session(mock_db)):
            with patch("app.scheduler.import_all_accounts", new_callable=AsyncMock, return_value=results):
                await _job_import_items()

        assert "avito_import" in _job_last_success

    @pytest.mark.asyncio
    async def test_with_errors(self):
        mock_db = AsyncMock()
        results = [
            {"account": "Acc1", "error": "timeout"},
        ]
        _job_last_success.pop("avito_import", None)

        with patch("app.scheduler.async_session", _fake_async_session(mock_db)):
            with patch("app.scheduler.import_all_accounts", new_callable=AsyncMock, return_value=results):
                await _job_import_items()

        assert "avito_import" in _job_last_success


# ---------------------------------------------------------------------------
# _job_refresh_tokens
# ---------------------------------------------------------------------------

class TestJobRefreshTokens:
    @pytest.mark.asyncio
    async def test_success(self):
        mock_db = AsyncMock()
        _job_last_success.pop("token_refresh", None)

        with patch("app.scheduler.async_session", _fake_async_session(mock_db)):
            with patch("app.scheduler.refresh_all_tokens", new_callable=AsyncMock, return_value={"refreshed": 2, "errors": 0}):
                await _job_refresh_tokens()

        assert "token_refresh" in _job_last_success


# ---------------------------------------------------------------------------
# _job_cleanup_removed
# ---------------------------------------------------------------------------

class TestJobCleanupRemoved:
    @pytest.mark.asyncio
    async def test_cleanup_deletes_old_products(self):
        mock_product = MagicMock()
        mock_product.id = 42
        mock_product.status = "removed"

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_product]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.delete = AsyncMock()
        mock_db.commit = AsyncMock()

        _job_last_success.pop("cleanup_removed", None)

        with patch("app.scheduler.async_session", _fake_async_session(mock_db)):
            with patch("os.path.isdir", return_value=True):
                with patch("shutil.rmtree"):
                    await _job_cleanup_removed()

        mock_db.delete.assert_called_once_with(mock_product)
        mock_db.commit.assert_called()
        assert "cleanup_removed" in _job_last_success

    @pytest.mark.asyncio
    async def test_cleanup_no_products(self):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        _job_last_success.pop("cleanup_removed", None)

        with patch("app.scheduler.async_session", _fake_async_session(mock_db)):
            await _job_cleanup_removed()

        assert "cleanup_removed" in _job_last_success


# ---------------------------------------------------------------------------
# _job_cleanup_old_feeds
# ---------------------------------------------------------------------------

class TestJobCleanupOldFeeds:
    @pytest.mark.asyncio
    async def test_removes_old_keeps_new(self, tmp_path):
        """Old timestamped XML files should be deleted; recent ones kept."""
        import os
        import time
        from app.config import settings as real_settings

        # Create old file (>30 days)
        old_file = tmp_path / "1_20260101_120000.xml"
        old_file.write_text("<xml>old</xml>")
        old_mtime = time.time() - 40 * 86400
        os.utime(old_file, (old_mtime, old_mtime))

        # Create recent file
        new_file = tmp_path / "1_20260415_120000.xml"
        new_file.write_text("<xml>new</xml>")

        # Create active feed (no underscore — current feed)
        active_file = tmp_path / "1.xml"
        active_file.write_text("<xml>active</xml>")
        os.utime(active_file, (old_mtime, old_mtime))  # old but no underscore

        orig_feeds = real_settings.FEEDS_DIR
        orig_retention = real_settings.FEED_RETENTION_DAYS
        try:
            real_settings.FEEDS_DIR = str(tmp_path)
            real_settings.FEED_RETENTION_DAYS = 30
            await _job_cleanup_old_feeds()
        finally:
            real_settings.FEEDS_DIR = orig_feeds
            real_settings.FEED_RETENTION_DAYS = orig_retention

        assert not old_file.exists(), "Old timestamped file should be deleted"
        assert new_file.exists(), "Recent file should be kept"
        assert active_file.exists(), "Active feed (no underscore) should be kept"

    @pytest.mark.asyncio
    async def test_empty_feeds_dir(self, tmp_path):
        """Should handle empty directory without errors."""
        from app.config import settings as real_settings

        orig = real_settings.FEEDS_DIR
        try:
            real_settings.FEEDS_DIR = str(tmp_path)
            await _job_cleanup_old_feeds()  # should not raise
        finally:
            real_settings.FEEDS_DIR = orig

    @pytest.mark.asyncio
    async def test_nonexistent_dir(self, tmp_path):
        """Should handle nonexistent directory without errors."""
        from app.config import settings as real_settings

        orig = real_settings.FEEDS_DIR
        try:
            real_settings.FEEDS_DIR = str(tmp_path / "nonexistent")
            await _job_cleanup_old_feeds()  # should not raise
        finally:
            real_settings.FEEDS_DIR = orig
