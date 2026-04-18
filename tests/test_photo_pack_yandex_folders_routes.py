"""Tests for app/routes/photo_pack_yandex_folders.py — folder CRUD + selection sync."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.db import get_db
from app.routes.photo_pack_yandex_folders import router


def _make_app(mock_db):
    app = FastAPI()
    app.include_router(router)
    async def override_db():
        yield mock_db
    app.dependency_overrides[get_db] = override_db
    return app


def _mock_pack(pid=1):
    p = MagicMock()
    p.id = pid
    return p


def _mock_folder(fid=1, pack_id=1, public_url="https://disk.yandex.ru/d/test", folder_name="test"):
    f = MagicMock()
    f.id = fid
    f.photo_pack_id = pack_id
    f.public_url = public_url
    f.public_key = public_url
    f.folder_name = folder_name
    f.last_synced_at = None
    f.error = None
    return f


def _mock_pack_image(img_id=1, pack_id=1, url="/media/photo_packs/1/0_test.jpg",
                     yandex_file_path=None, yandex_folder_id=None,
                     download_status="ready", sort_order=0):
    img = MagicMock()
    img.id = img_id
    img.pack_id = pack_id
    img.url = url
    img.file_path = url.replace("/media/", "./media/") if url else ""
    img.sort_order = sort_order
    img.yandex_file_path = yandex_file_path
    img.yandex_folder_id = yandex_folder_id
    img.download_status = download_status
    img.source_type = "yandex_disk" if yandex_file_path else "local"
    img.download_error = None
    img.download_attempts = 0
    return img


def _mock_scalars(items):
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = items
    result = MagicMock()
    result.scalars.return_value = scalars_mock
    return result


def _mock_scalar_one_or_none(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


# ---------------------------------------------------------------------------
# GET /api/photo-packs/{id}/yandex-folders
# ---------------------------------------------------------------------------

class TestGetPackYandexFolders:
    @pytest.mark.asyncio
    async def test_pack_not_found(self):
        db = AsyncMock()
        db.get = AsyncMock(return_value=None)
        app = _make_app(db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/photo-packs/999/yandex-folders")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_no_folders(self):
        db = AsyncMock()
        db.get = AsyncMock(return_value=_mock_pack())
        db.execute = AsyncMock(side_effect=[_mock_scalars([]), _mock_scalars([])])
        db.commit = AsyncMock()
        app = _make_app(db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/photo-packs/1/yandex-folders")
        assert resp.status_code == 200
        assert resp.json()["folders"] == []

    @pytest.mark.asyncio
    @patch("app.routes.photo_pack_yandex_folders.list_folder", new_callable=AsyncMock)
    async def test_with_folders_ydisk_reachable(self, mock_list):
        mock_list.return_value = [
            {"path": "/photo.jpg", "name": "photo.jpg", "preview_url": "https://p/1",
             "size": 1000, "md5": "abc", "mime_type": "image/jpeg"},
        ]
        folder = _mock_folder()
        db = AsyncMock()
        db.get = AsyncMock(return_value=_mock_pack())
        db.execute = AsyncMock(side_effect=[_mock_scalars([folder]), _mock_scalars([])])
        db.commit = AsyncMock()
        app = _make_app(db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/photo-packs/1/yandex-folders")
        data = resp.json()
        assert data["ok"] is True
        assert len(data["folders"]) == 1
        assert len(data["folders"][0]["files"]) == 1
        assert data["folders"][0]["error"] is None

    @pytest.mark.asyncio
    @patch("app.routes.photo_pack_yandex_folders.list_folder", new_callable=AsyncMock)
    async def test_ydisk_unreachable_no_500(self, mock_list):
        mock_list.side_effect = Exception("Connection refused")
        folder = _mock_folder()
        db = AsyncMock()
        db.get = AsyncMock(return_value=_mock_pack())
        db.execute = AsyncMock(side_effect=[_mock_scalars([folder]), _mock_scalars([])])
        db.commit = AsyncMock()
        app = _make_app(db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/photo-packs/1/yandex-folders")
        assert resp.status_code == 200
        data = resp.json()
        assert data["folders"][0]["files"] == []
        assert "Connection refused" in data["folders"][0]["error"]


# ---------------------------------------------------------------------------
# POST /api/photo-packs/{id}/yandex-folders
# ---------------------------------------------------------------------------

class TestAddPackYandexFolder:
    @pytest.mark.asyncio
    async def test_pack_not_found(self):
        db = AsyncMock()
        db.get = AsyncMock(return_value=None)
        app = _make_app(db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/photo-packs/999/yandex-folders",
                                json={"public_url": "https://disk.yandex.ru/d/abc"})
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_invalid_url(self):
        db = AsyncMock()
        db.get = AsyncMock(return_value=_mock_pack())
        app = _make_app(db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/photo-packs/1/yandex-folders",
                                json={"public_url": "https://google.com/not-yandex"})
        assert resp.status_code == 400
        assert "Not a Yandex" in resp.json()["error"]

    @pytest.mark.asyncio
    async def test_rejects_client_disk_url(self):
        """Personal /client/disk/ URLs should be rejected with 400."""
        db = AsyncMock()
        db.get = AsyncMock(return_value=_mock_pack())
        app = _make_app(db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/photo-packs/1/yandex-folders",
                                json={"public_url": "https://disk.yandex.ru/client/disk/Folder/Sub"})
        assert resp.status_code == 400
        assert "публичная" in resp.json()["error"]

    @pytest.mark.asyncio
    @patch("app.routes.photo_pack_yandex_folders.list_folder", new_callable=AsyncMock)
    async def test_handles_yandex_400_gracefully(self, mock_list):
        """Y.Disk 400 response should return 400, not 500."""
        import httpx
        mock_list.side_effect = httpx.HTTPStatusError(
            "400 BAD REQUEST",
            request=httpx.Request("GET", "https://mock"),
            response=httpx.Response(400),
        )
        db = AsyncMock()
        db.get = AsyncMock(return_value=_mock_pack())
        app = _make_app(db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/photo-packs/1/yandex-folders",
                                json={"public_url": "https://disk.yandex.ru/d/bad"})
        assert resp.status_code == 400
        assert "не найдена" in resp.json()["error"]

    @pytest.mark.asyncio
    @patch("app.routes.photo_pack_yandex_folders.list_folder", new_callable=AsyncMock)
    async def test_folder_not_accessible(self, mock_list):
        mock_list.side_effect = ValueError("Folder not found or not public")
        db = AsyncMock()
        db.get = AsyncMock(return_value=_mock_pack())
        app = _make_app(db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/photo-packs/1/yandex-folders",
                                json={"public_url": "https://disk.yandex.ru/d/bad"})
        assert resp.status_code == 400
        assert "недоступна" in resp.json()["error"]

    @pytest.mark.asyncio
    @patch("app.routes.photo_pack_yandex_folders.list_folder", new_callable=AsyncMock)
    async def test_success(self, mock_list):
        mock_list.return_value = [
            {"path": "/p.jpg", "name": "p.jpg", "preview_url": "https://p",
             "size": 500, "md5": "x", "mime_type": "image/jpeg"},
        ]
        db = AsyncMock()
        db.get = AsyncMock(return_value=_mock_pack())
        db.add = MagicMock()
        db.commit = AsyncMock()
        app = _make_app(db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/photo-packs/1/yandex-folders",
                                json={"public_url": "https://disk.yandex.ru/d/test", "folder_name": "F1"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["ok"] is True
        assert len(data["files"]) == 1


# ---------------------------------------------------------------------------
# DELETE /api/photo-packs/{id}/yandex-folders/{fid}
# ---------------------------------------------------------------------------

class TestDeletePackYandexFolder:
    @pytest.mark.asyncio
    async def test_not_found(self):
        db = AsyncMock()
        db.get = AsyncMock(return_value=None)
        app = _make_app(db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.delete("/api/photo-packs/1/yandex-folders/999")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_without_images(self):
        folder = _mock_folder()
        db = AsyncMock()
        db.get = AsyncMock(return_value=folder)
        db.delete = AsyncMock()
        db.commit = AsyncMock()
        app = _make_app(db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.delete("/api/photo-packs/1/yandex-folders/1")
        assert resp.status_code == 200
        db.delete.assert_awaited_once_with(folder)

    @pytest.mark.asyncio
    @patch("app.routes.photo_pack_yandex_folders._delete_local_file")
    async def test_delete_with_images(self, mock_del_file):
        folder = _mock_folder()
        img = _mock_pack_image(yandex_folder_id=1, url="/media/photo_packs/1/0_x.jpg")
        db = AsyncMock()
        db.get = AsyncMock(return_value=folder)
        db.execute = AsyncMock(return_value=_mock_scalars([img]))
        db.delete = AsyncMock()
        db.commit = AsyncMock()
        app = _make_app(db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.delete("/api/photo-packs/1/yandex-folders/1?delete_images=true")
        assert resp.status_code == 200
        mock_del_file.assert_called_once_with(img.url)
        assert db.delete.await_count == 2  # img + folder


# ---------------------------------------------------------------------------
# PUT /api/photo-packs/{id}/yandex-folders/{fid}/selection
# ---------------------------------------------------------------------------

class TestUpdatePackSelection:
    @pytest.mark.asyncio
    async def test_folder_not_found(self):
        db = AsyncMock()
        db.get = AsyncMock(return_value=None)
        app = _make_app(db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.put("/api/photo-packs/1/yandex-folders/999/selection",
                               json={"selected_paths": ["/a.jpg"]})
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_adds_new_rows(self):
        folder = _mock_folder()
        db = AsyncMock()
        db.get = AsyncMock(return_value=folder)
        db.execute = AsyncMock(side_effect=[
            _mock_scalars([]),                # existing images for folder
            _mock_scalar_one_or_none(None),   # max sort_order
            _mock_scalars([]),                 # result after commit
        ])
        db.add = MagicMock()
        db.commit = AsyncMock()
        app = _make_app(db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.put("/api/photo-packs/1/yandex-folders/1/selection",
                               json={"selected_paths": ["/a.jpg", "/b.jpg"]})
        assert resp.status_code == 200
        data = resp.json()
        assert data["added"] == 2
        assert db.add.call_count == 2

    @pytest.mark.asyncio
    @patch("app.routes.photo_pack_yandex_folders._delete_local_file")
    async def test_removes_deselected(self, mock_del):
        folder = _mock_folder()
        existing_img = _mock_pack_image(
            yandex_file_path="/old.jpg", yandex_folder_id=1,
            url="/media/photo_packs/1/0_old.jpg",
        )
        db = AsyncMock()
        db.get = AsyncMock(return_value=folder)
        db.execute = AsyncMock(side_effect=[
            _mock_scalars([existing_img]),     # existing
            _mock_scalar_one_or_none(0),       # max sort_order
            _mock_scalars([]),                  # result after
        ])
        db.delete = AsyncMock()
        db.commit = AsyncMock()
        db.add = MagicMock()
        app = _make_app(db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.put("/api/photo-packs/1/yandex-folders/1/selection",
                               json={"selected_paths": []})  # deselect all
        assert resp.status_code == 200
        db.delete.assert_awaited_once_with(existing_img)
        mock_del.assert_called_once()

    @pytest.mark.asyncio
    async def test_keeps_existing_paths(self):
        folder = _mock_folder()
        existing_img = _mock_pack_image(
            yandex_file_path="/keep.jpg", yandex_folder_id=1,
        )
        db = AsyncMock()
        db.get = AsyncMock(return_value=folder)
        db.execute = AsyncMock(side_effect=[
            _mock_scalars([existing_img]),     # existing
            _mock_scalar_one_or_none(0),       # max sort_order
            _mock_scalars([existing_img]),      # result after
        ])
        db.commit = AsyncMock()
        db.add = MagicMock()
        db.delete = AsyncMock()
        app = _make_app(db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.put("/api/photo-packs/1/yandex-folders/1/selection",
                               json={"selected_paths": ["/keep.jpg"]})
        assert resp.status_code == 200
        assert resp.json()["added"] == 0
        db.add.assert_not_called()
        db.delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_new_rows_have_correct_fields(self):
        folder = _mock_folder()
        db = AsyncMock()
        db.get = AsyncMock(return_value=folder)
        db.execute = AsyncMock(side_effect=[
            _mock_scalars([]),
            _mock_scalar_one_or_none(None),
            _mock_scalars([]),
        ])
        added_objects = []
        db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))
        db.commit = AsyncMock()
        app = _make_app(db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            await c.put("/api/photo-packs/1/yandex-folders/1/selection",
                        json={"selected_paths": ["/new.jpg"]})
        assert len(added_objects) == 1
        img = added_objects[0]
        assert img.source_type == "yandex_disk"
        assert img.download_status == "pending"
        assert img.file_path == ""
        assert img.url == ""
        assert img.yandex_file_path == "/new.jpg"


# ---------------------------------------------------------------------------
# PUT /api/photo-packs/{id}/images/order
# ---------------------------------------------------------------------------

class TestUpdatePackImageOrder:
    @pytest.mark.asyncio
    async def test_empty_ids(self):
        db = AsyncMock()
        app = _make_app(db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.put("/api/photo-packs/1/images/order",
                               json={"ordered_image_ids": []})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_success(self):
        img1 = _mock_pack_image(img_id=10, sort_order=0)
        img2 = _mock_pack_image(img_id=20, sort_order=1)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_scalars([img1, img2]))
        db.commit = AsyncMock()
        app = _make_app(db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.put("/api/photo-packs/1/images/order",
                               json={"ordered_image_ids": [20, 10]})
        assert resp.status_code == 200
        assert img2.sort_order == 0
        assert img1.sort_order == 1

    @pytest.mark.asyncio
    async def test_wrong_pack_rejected(self):
        img1 = _mock_pack_image(img_id=10, pack_id=2)  # pack 2, not 1
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_scalars([]))  # nothing found for pack 1
        app = _make_app(db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.put("/api/photo-packs/1/images/order",
                               json={"ordered_image_ids": [10]})
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# PATCH /api/photo-packs/{id}/images/{iid}/retry-download
# ---------------------------------------------------------------------------

class TestRetryPackDownload:
    @pytest.mark.asyncio
    async def test_not_found(self):
        db = AsyncMock()
        db.get = AsyncMock(return_value=None)
        app = _make_app(db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.patch("/api/photo-packs/1/images/999/retry-download")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_not_failed(self):
        img = _mock_pack_image(download_status="ready")
        db = AsyncMock()
        db.get = AsyncMock(return_value=img)
        app = _make_app(db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.patch("/api/photo-packs/1/images/1/retry-download")
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_success(self):
        img = _mock_pack_image(download_status="failed")
        img.download_error = "timeout"
        img.download_attempts = 3
        db = AsyncMock()
        db.get = AsyncMock(return_value=img)
        db.commit = AsyncMock()
        app = _make_app(db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.patch("/api/photo-packs/1/images/1/retry-download")
        assert resp.status_code == 200
        assert img.download_status == "pending"
        assert img.download_error is None
        assert img.download_attempts == 0
