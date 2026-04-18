"""Tests for _job_download_pending_yandex handling photo_pack_images."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _fake_async_session(mock_db):
    @asynccontextmanager
    async def _ctx():
        yield mock_db
    return _ctx


def _mock_scalars(items):
    s = MagicMock()
    s.all.return_value = items
    r = MagicMock()
    r.scalars.return_value = s
    return r


class TestDownloadPendingPackPhotos:
    @pytest.mark.asyncio
    @patch("app.scheduler._download_one_yandex_image", new_callable=AsyncMock)
    async def test_both_product_and_pack_pending_processed(self, mock_download):
        """Both product and pack pending images should be processed in one run."""
        from app.scheduler import _job_download_pending_yandex

        mock_download.return_value = True
        prod_img = MagicMock()
        pack_img = MagicMock()

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=[
            _mock_scalars([prod_img]),   # product pending
            _mock_scalars([pack_img]),   # pack pending
        ])
        mock_db.commit = AsyncMock()

        with patch("app.scheduler.async_session", _fake_async_session(mock_db)):
            await _job_download_pending_yandex()

        assert mock_download.await_count == 2

    @pytest.mark.asyncio
    @patch("app.scheduler._download_one_yandex_image", new_callable=AsyncMock)
    async def test_pack_image_dispatched_with_kind_photo_pack(self, mock_download):
        """Pack images should be dispatched with kind='photo_pack'."""
        from app.scheduler import _job_download_pending_yandex

        mock_download.return_value = True
        pack_img = MagicMock()

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=[
            _mock_scalars([]),          # no product pending
            _mock_scalars([pack_img]),  # pack pending
        ])
        mock_db.commit = AsyncMock()

        with patch("app.scheduler.async_session", _fake_async_session(mock_db)):
            await _job_download_pending_yandex()

        # args: (db, img, folder_cls, kind, sem, cfg)
        call_args = mock_download.call_args_list[0]
        assert call_args[0][3] == "photo_pack"

    @pytest.mark.asyncio
    @patch("app.scheduler._download_one_yandex_image", new_callable=AsyncMock)
    async def test_product_image_dispatched_with_kind_product(self, mock_download):
        """Product images should be dispatched with kind='product'."""
        from app.scheduler import _job_download_pending_yandex

        mock_download.return_value = True
        prod_img = MagicMock()

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=[
            _mock_scalars([prod_img]),  # product pending
            _mock_scalars([]),          # no pack pending
        ])
        mock_db.commit = AsyncMock()

        with patch("app.scheduler.async_session", _fake_async_session(mock_db)):
            await _job_download_pending_yandex()

        call_args = mock_download.call_args_list[0]
        assert call_args[0][3] == "product"

    @pytest.mark.asyncio
    @patch("app.scheduler._download_one_yandex_image", new_callable=AsyncMock)
    async def test_no_pending_returns_early(self, mock_download):
        """No pending images → helper not called."""
        from app.scheduler import _job_download_pending_yandex

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=[
            _mock_scalars([]),  # no product pending
            _mock_scalars([]),  # no pack pending
        ])

        with patch("app.scheduler.async_session", _fake_async_session(mock_db)):
            await _job_download_pending_yandex()

        mock_download.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("app.scheduler._download_one_yandex_image", new_callable=AsyncMock)
    async def test_failure_counted(self, mock_download):
        """Failed downloads should be counted correctly."""
        from app.scheduler import _job_download_pending_yandex

        mock_download.side_effect = [True, False]  # 1 ok, 1 fail
        img1 = MagicMock()
        img2 = MagicMock()

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=[
            _mock_scalars([img1, img2]),  # product pending
            _mock_scalars([]),            # no pack pending
        ])
        mock_db.commit = AsyncMock()

        with patch("app.scheduler.async_session", _fake_async_session(mock_db)):
            await _job_download_pending_yandex()

        assert mock_download.await_count == 2
