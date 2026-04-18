"""Tests for app/routes/yandex_folders.py — folder CRUD + selection sync."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.db import get_db
from app.routes.yandex_folders import router


def _make_app(mock_db):
    app = FastAPI()
    app.include_router(router)
    async def override_db():
        yield mock_db
    app.dependency_overrides[get_db] = override_db
    return app


def _mock_product(pid=1):
    p = MagicMock()
    p.id = pid
    return p


def _mock_folder(fid=1, product_id=1, public_url="https://disk.yandex.ru/d/test", folder_name="test"):
    f = MagicMock()
    f.id = fid
    f.product_id = product_id
    f.public_url = public_url
    f.public_key = public_url
    f.folder_name = folder_name
    f.last_synced_at = None
    f.error = None
    return f


def _mock_scalars(items):
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = items
    result = MagicMock()
    result.scalars.return_value = scalars_mock
    return result


# ---------------------------------------------------------------------------
# POST /api/products/{id}/yandex-folders
# ---------------------------------------------------------------------------

class TestAddYandexFolder:
    @pytest.mark.asyncio
    async def test_product_not_found(self):
        db = AsyncMock()
        db.get = AsyncMock(return_value=None)
        app = _make_app(db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                "/api/products/999/yandex-folders",
                json={"public_url": "https://disk.yandex.ru/d/abc"},
            )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_invalid_url(self):
        db = AsyncMock()
        db.get = AsyncMock(return_value=_mock_product())
        app = _make_app(db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                "/api/products/1/yandex-folders",
                json={"public_url": "https://google.com/not-yandex"},
            )
        assert resp.status_code == 400
        assert "Not a Yandex" in resp.json()["error"]

    @pytest.mark.asyncio
    async def test_rejects_client_disk_url(self):
        """Personal /client/disk/ URLs should be rejected with 400."""
        db = AsyncMock()
        db.get = AsyncMock(return_value=_mock_product())
        app = _make_app(db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                "/api/products/1/yandex-folders",
                json={"public_url": "https://disk.yandex.ru/client/disk/Folder/Sub"},
            )
        assert resp.status_code == 400
        assert "публичная" in resp.json()["error"]

    @pytest.mark.asyncio
    @patch("app.routes.yandex_folders.list_folder", new_callable=AsyncMock)
    async def test_handles_yandex_400_gracefully(self, mock_list):
        """Y.Disk 400 response should return 400, not 500."""
        import httpx
        mock_list.side_effect = httpx.HTTPStatusError(
            "400 BAD REQUEST",
            request=httpx.Request("GET", "https://mock"),
            response=httpx.Response(400),
        )
        db = AsyncMock()
        db.get = AsyncMock(return_value=_mock_product())
        app = _make_app(db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                "/api/products/1/yandex-folders",
                json={"public_url": "https://disk.yandex.ru/d/bad"},
            )
        assert resp.status_code == 400
        assert "не найдена" in resp.json()["error"]

    @pytest.mark.asyncio
    @patch("app.routes.yandex_folders.list_folder", new_callable=AsyncMock)
    async def test_folder_not_accessible(self, mock_list):
        mock_list.side_effect = ValueError("Folder not found or not public")
        db = AsyncMock()
        db.get = AsyncMock(return_value=_mock_product())
        app = _make_app(db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                "/api/products/1/yandex-folders",
                json={"public_url": "https://disk.yandex.ru/d/nonexistent"},
            )
        assert resp.status_code == 400
        assert "недоступна" in resp.json()["error"]

    @pytest.mark.asyncio
    @patch("app.routes.yandex_folders.list_folder", new_callable=AsyncMock)
    async def test_success(self, mock_list):
        mock_list.return_value = [
            {"path": "/photo1.jpg", "name": "photo1.jpg", "preview_url": "https://prev/1",
             "size": 1000, "md5": "abc", "mime_type": "image/jpeg"},
        ]
        db = AsyncMock()
        db.get = AsyncMock(return_value=_mock_product())
        db.add = MagicMock()
        db.commit = AsyncMock()
        app = _make_app(db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                "/api/products/1/yandex-folders",
                json={"public_url": "https://disk.yandex.ru/d/test", "folder_name": "My folder"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert len(data["files"]) == 1
        assert data["files"][0]["name"] == "photo1.jpg"
        assert data["files"][0]["selected"] is False


# ---------------------------------------------------------------------------
# DELETE /api/products/{id}/yandex-folders/{folder_id}
# ---------------------------------------------------------------------------

class TestDeleteYandexFolder:
    @pytest.mark.asyncio
    async def test_not_found(self):
        db = AsyncMock()
        db.get = AsyncMock(return_value=None)
        app = _make_app(db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.delete("/api/products/1/yandex-folders/999")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_wrong_product(self):
        folder = _mock_folder(fid=1, product_id=2)  # belongs to product 2
        db = AsyncMock()
        db.get = AsyncMock(return_value=folder)
        app = _make_app(db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.delete("/api/products/1/yandex-folders/1")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_success(self):
        folder = _mock_folder(fid=1, product_id=1)
        db = AsyncMock()
        db.get = AsyncMock(return_value=folder)
        db.delete = AsyncMock()
        db.commit = AsyncMock()
        app = _make_app(db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.delete("/api/products/1/yandex-folders/1")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        db.delete.assert_awaited_once_with(folder)


# ---------------------------------------------------------------------------
# PUT /api/products/{id}/images/order
# ---------------------------------------------------------------------------

class TestUpdateImageOrder:
    @pytest.mark.asyncio
    async def test_empty_ids(self):
        db = AsyncMock()
        app = _make_app(db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.put(
                "/api/products/1/images/order",
                json={"ordered_image_ids": []},
            )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_success(self):
        img1 = MagicMock()
        img1.id = 10
        img1.sort_order = 0
        img1.is_main = True
        img2 = MagicMock()
        img2.id = 20
        img2.sort_order = 1
        img2.is_main = False

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_scalars([img1, img2]))
        db.commit = AsyncMock()
        app = _make_app(db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.put(
                "/api/products/1/images/order",
                json={"ordered_image_ids": [20, 10]},  # swap order
            )
        assert resp.status_code == 200
        # img2 should now be first (main)
        assert img2.sort_order == 0
        assert img2.is_main is True
        assert img1.sort_order == 1
        assert img1.is_main is False


# ---------------------------------------------------------------------------
# PATCH retry-download
# ---------------------------------------------------------------------------

class TestRetryDownload:
    @pytest.mark.asyncio
    async def test_not_found(self):
        db = AsyncMock()
        db.get = AsyncMock(return_value=None)
        app = _make_app(db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.patch("/api/products/1/images/999/retry-download")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_not_in_failed_state(self):
        img = MagicMock()
        img.id = 1
        img.product_id = 1
        img.download_status = "ready"
        db = AsyncMock()
        db.get = AsyncMock(return_value=img)
        app = _make_app(db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.patch("/api/products/1/images/1/retry-download")
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_success(self):
        img = MagicMock()
        img.id = 1
        img.product_id = 1
        img.download_status = "failed"
        img.download_error = "timeout"
        db = AsyncMock()
        db.get = AsyncMock(return_value=img)
        db.commit = AsyncMock()
        app = _make_app(db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.patch("/api/products/1/images/1/retry-download")
        assert resp.status_code == 200
        assert img.download_status == "pending"
        assert img.download_error is None
