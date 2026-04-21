"""Tests for _job_sync_yandex_folders handling photo_pack folders."""

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


class TestSyncYandexFoldersPacks:
    @pytest.mark.asyncio
    @patch("app.scheduler._sync_one_folder_kind", new_callable=AsyncMock)
    async def test_both_kinds_processed(self, mock_sync):
        """Both product and pack folders should be synced in one run."""
        from app.scheduler import _job_sync_yandex_folders

        mock_sync.return_value = (1, 1)

        mock_db = AsyncMock()
        mock_db.commit = AsyncMock()

        with patch("app.scheduler.async_session", _fake_async_session(mock_db)):
            await _job_sync_yandex_folders()

        assert mock_sync.await_count == 2

    @pytest.mark.asyncio
    async def test_sync_detects_deleted_files(self):
        """File removed from Y.Disk → corresponding image row deleted."""
        from app.scheduler import _sync_one_folder_kind

        folder = MagicMock()
        folder.id = 1
        folder.public_url = "https://disk.yandex.ru/d/test"
        folder.last_synced_at = None
        folder.error = None

        img_gone = MagicMock()
        img_gone.yandex_file_path = "/deleted.jpg"
        img_gone.url = "/media/photo_packs/1/0_deleted.jpg"

        img_still = MagicMock()
        img_still.yandex_file_path = "/still_there.jpg"
        img_still.url = "/media/photo_packs/1/1_still.jpg"

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=[
            _mock_scalars([folder]),
            _mock_scalars([img_gone, img_still]),
        ])
        mock_db.delete = AsyncMock()
        mock_db.commit = AsyncMock()

        from app.models.photo_pack_yandex_folder import PhotoPackYandexFolder
        from app.models.photo_pack_image import PhotoPackImage

        with patch("app.services.yandex_disk.list_folder", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = [{"path": "/still_there.jpg", "name": "still_there.jpg"}]
            cfg = MagicMock()
            cfg.MEDIA_DIR = "/tmp/test_media"
            with patch("os.remove"):
                synced, total = await _sync_one_folder_kind(
                    mock_db, PhotoPackYandexFolder, PhotoPackImage, "yandex_folder_id", cfg,
                )

        assert synced == 1
        mock_db.delete.assert_awaited_once_with(img_gone)

    @pytest.mark.asyncio
    async def test_sync_ydisk_error_sets_folder_error(self):
        """Y.Disk folder error → folder.error set, no image deletions."""
        from app.scheduler import _sync_one_folder_kind

        folder = MagicMock()
        folder.id = 1
        folder.public_url = "https://disk.yandex.ru/d/test"
        folder.last_synced_at = None
        folder.error = None

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=_mock_scalars([folder]))
        mock_db.delete = AsyncMock()
        mock_db.commit = AsyncMock()

        from app.models.photo_pack_yandex_folder import PhotoPackYandexFolder
        from app.models.photo_pack_image import PhotoPackImage

        with patch("app.services.yandex_disk.list_folder", new_callable=AsyncMock, side_effect=Exception("timeout")):
            cfg = MagicMock()
            synced, total = await _sync_one_folder_kind(
                mock_db, PhotoPackYandexFolder, PhotoPackImage, "yandex_folder_id", cfg,
            )

        assert synced == 0
        assert "timeout" in folder.error
        mock_db.delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_sync_auto_adds_new_files(self):
        """New file in Y.Disk folder → PhotoPackImage created with pending status."""
        from app.scheduler import _sync_one_folder_kind
        from app.models.photo_pack_yandex_folder import PhotoPackYandexFolder
        from app.models.photo_pack_image import PhotoPackImage

        folder = MagicMock()
        folder.id = 10
        folder.public_url = "https://disk.yandex.ru/d/test"
        folder.photo_pack_id = 5
        folder.last_synced_at = None
        folder.error = None

        # Existing image — already downloaded
        img_existing = MagicMock()
        img_existing.yandex_file_path = "/old.jpg"
        img_existing.url = "/media/photo_packs/5/0_old.jpg"

        # Mock DB: 1) folders query, 2) existing images, 3) max sort_order
        max_order = MagicMock()
        max_order.scalar_one_or_none.return_value = 3

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=[
            _mock_scalars([folder]),
            _mock_scalars([img_existing]),
            max_order,
        ])
        mock_db.add = MagicMock()

        with patch("app.services.yandex_disk.list_folder", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = [
                {"path": "/old.jpg", "name": "old.jpg"},
                {"path": "/new_photo.jpg", "name": "new_photo.jpg"},
            ]
            cfg = MagicMock()
            cfg.MEDIA_DIR = "/tmp/test_media"
            synced, total = await _sync_one_folder_kind(
                mock_db, PhotoPackYandexFolder, PhotoPackImage, "yandex_folder_id", cfg,
                parent_id_attr="pack_id", folder_parent_id_attr="photo_pack_id",
            )

        assert synced == 1
        # Should have added one new image
        assert mock_db.add.call_count == 1
        added_img = mock_db.add.call_args[0][0]
        assert isinstance(added_img, PhotoPackImage)
        assert added_img.yandex_file_path == "/new_photo.jpg"
        assert added_img.download_status == "pending"
        assert added_img.pack_id == 5
        assert added_img.sort_order == 4  # max was 3, so next is 4
        # Existing image NOT deleted
        mock_db.delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_sync_removes_and_adds_simultaneously(self):
        """Removed file deleted, new file added — both in same sync pass."""
        from app.scheduler import _sync_one_folder_kind
        from app.models.photo_pack_yandex_folder import PhotoPackYandexFolder
        from app.models.photo_pack_image import PhotoPackImage

        folder = MagicMock()
        folder.id = 10
        folder.public_url = "https://disk.yandex.ru/d/test"
        folder.photo_pack_id = 5
        folder.last_synced_at = None
        folder.error = None

        img_gone = MagicMock()
        img_gone.yandex_file_path = "/removed.jpg"
        img_gone.url = "/media/photo_packs/5/0_removed.jpg"

        img_kept = MagicMock()
        img_kept.yandex_file_path = "/kept.jpg"
        img_kept.url = "/media/photo_packs/5/1_kept.jpg"

        max_order = MagicMock()
        max_order.scalar_one_or_none.return_value = 1

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=[
            _mock_scalars([folder]),
            _mock_scalars([img_gone, img_kept]),
            max_order,
        ])
        mock_db.add = MagicMock()
        mock_db.delete = AsyncMock()

        with patch("app.services.yandex_disk.list_folder", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = [
                {"path": "/kept.jpg", "name": "kept.jpg"},
                {"path": "/brand_new.jpg", "name": "brand_new.jpg"},
            ]
            cfg = MagicMock()
            cfg.MEDIA_DIR = "/tmp/test_media"
            with patch("os.remove"):
                synced, total = await _sync_one_folder_kind(
                    mock_db, PhotoPackYandexFolder, PhotoPackImage, "yandex_folder_id", cfg,
                    parent_id_attr="pack_id", folder_parent_id_attr="photo_pack_id",
                )

        assert synced == 1
        # Removed image deleted
        mock_db.delete.assert_awaited_once_with(img_gone)
        # New image added
        assert mock_db.add.call_count == 1
        added = mock_db.add.call_args[0][0]
        assert added.yandex_file_path == "/brand_new.jpg"
        assert added.download_status == "pending"
