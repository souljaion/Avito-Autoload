"""Unit tests for app/routes/photo_packs.py"""

import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.db import get_db
from app.routes.photo_packs import router, _thumb_url


def _make_app(mock_db):
    app = FastAPI()
    app.include_router(router)

    async def override_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_db
    return app


def _mock_pack(pack_id=1, name="Pack A", model_id=10, images=None):
    pack = MagicMock()
    pack.id = pack_id
    pack.name = name
    pack.model_id = model_id
    pack.images = images or []
    return pack


def _mock_pack_image(img_id=1, url="/media/photo_packs/1/0_test.jpg", sort_order=0):
    img = MagicMock()
    img.id = img_id
    img.url = url
    img.sort_order = sort_order
    img.download_status = "ready"
    img.download_error = None
    img.yandex_file_path = None
    img.source_type = "local"
    return img


def _mock_scalars(items, unique=False):
    """Build a result mock whose .scalars().all() (or .scalars().unique().all()) returns items."""
    scalars_mock = MagicMock()
    if unique:
        unique_mock = MagicMock()
        unique_mock.all.return_value = items
        scalars_mock.unique.return_value = unique_mock
    scalars_mock.all.return_value = items
    result = MagicMock()
    result.scalars.return_value = scalars_mock
    return result


# ---------------------------------------------------------------------------
# _thumb_url helper
# ---------------------------------------------------------------------------

def test_thumb_url():
    assert _thumb_url("/media/photo_packs/1/0_foo.jpg") == "/media/photo_packs/1/0_foo_thumb.jpg"
    assert _thumb_url("/media/photo_packs/1/img.png") == "/media/photo_packs/1/img_thumb.png"


# ---------------------------------------------------------------------------
# GET /photo-packs  (list)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_packs_empty():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_mock_scalars([], unique=True))

    app = _make_app(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/photo-packs")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["packs"] == []


@pytest.mark.asyncio
async def test_list_packs_returns_data():
    img = _mock_pack_image(img_id=5, url="/media/photo_packs/1/0_shoe.jpg", sort_order=0)
    pack = _mock_pack(pack_id=1, name="Pack A", model_id=10, images=[img])

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_mock_scalars([pack], unique=True))

    app = _make_app(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/photo-packs")
    data = resp.json()
    assert data["ok"] is True
    assert len(data["packs"]) == 1
    assert data["packs"][0]["name"] == "Pack A"
    assert data["packs"][0]["image_count"] == 1
    assert data["packs"][0]["images"][0]["thumb_url"].endswith("_thumb.jpg")


@pytest.mark.asyncio
async def test_list_packs_filter_by_model_id():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_mock_scalars([], unique=True))

    app = _make_app(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/photo-packs?model_id=10")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


# ---------------------------------------------------------------------------
# POST /photo-packs  (create)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_pack():
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()

    app = _make_app(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/photo-packs", data={"name": "New Pack", "model_id": "10"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["name"] == "New Pack"
    db.add.assert_called_once()
    db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# DELETE /photo-packs/{id}
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_pack_not_found():
    db = AsyncMock()
    db.get = AsyncMock(return_value=None)

    app = _make_app(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.delete("/photo-packs/999")
    assert resp.status_code == 404
    assert resp.json()["ok"] is False


@pytest.mark.asyncio
@patch("app.routes.photo_packs.shutil.rmtree")
@patch("app.routes.photo_packs.os.path.isdir", return_value=True)
async def test_delete_pack_success(mock_isdir, mock_rmtree):
    pack = _mock_pack(pack_id=1)
    db = AsyncMock()
    db.get = AsyncMock(return_value=pack)
    db.delete = AsyncMock()
    db.commit = AsyncMock()

    app = _make_app(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.delete("/photo-packs/1")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    db.delete.assert_awaited_once_with(pack)
    mock_rmtree.assert_called_once()


@pytest.mark.asyncio
@patch("app.routes.photo_packs.shutil.rmtree")
@patch("app.routes.photo_packs.os.path.isdir", return_value=False)
async def test_delete_pack_no_directory(mock_isdir, mock_rmtree):
    pack = _mock_pack(pack_id=2)
    db = AsyncMock()
    db.get = AsyncMock(return_value=pack)
    db.delete = AsyncMock()
    db.commit = AsyncMock()

    app = _make_app(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.delete("/photo-packs/2")
    assert resp.status_code == 200
    mock_rmtree.assert_not_called()


# ---------------------------------------------------------------------------
# POST /photo-packs/{id}/upload  (upload images)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch("app.routes.photo_packs.aiofiles.open")
@patch("app.routes.photo_packs.os.makedirs")
@patch("app.routes.photo_packs.process_image_async", new_callable=AsyncMock)
@patch("app.routes.photo_packs.make_thumbnail_async", new_callable=AsyncMock)
async def test_upload_photos_success(mock_thumb, mock_process, mock_makedirs, mock_aio_open):
    mock_process.return_value = b"processed_jpeg"
    mock_thumb.return_value = b"thumb_jpeg"

    # Mock aiofiles context manager
    file_mock = AsyncMock()
    file_mock.write = AsyncMock()
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=file_mock)
    cm.__aexit__ = AsyncMock(return_value=False)
    mock_aio_open.return_value = cm

    pack = _mock_pack(pack_id=1)
    db = AsyncMock()
    db.get = AsyncMock(return_value=pack)
    # execute for existing images query
    db.execute = AsyncMock(return_value=_mock_scalars([]))
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    app = _make_app(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            "/photo-packs/1/upload",
            files=[("files", ("shoe.jpg", b"fake_image_data", "image/jpeg"))],
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert len(data["images"]) == 1
    assert "url" in data["images"][0]


@pytest.mark.asyncio
async def test_upload_photos_pack_not_found():
    db = AsyncMock()
    db.get = AsyncMock(return_value=None)

    app = _make_app(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            "/photo-packs/999/upload",
            files=[("files", ("shoe.jpg", b"fake", "image/jpeg"))],
        )
    assert resp.status_code == 404
    assert resp.json()["ok"] is False


@pytest.mark.asyncio
async def test_upload_photos_too_large():
    pack = _mock_pack(pack_id=1)
    db = AsyncMock()
    db.get = AsyncMock(return_value=pack)
    db.execute = AsyncMock(return_value=_mock_scalars([]))

    app = _make_app(db)
    # Create a file larger than 20 MB
    big_data = b"x" * (21 * 1024 * 1024)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            "/photo-packs/1/upload",
            files=[("files", ("big.jpg", big_data, "image/jpeg"))],
        )
    assert resp.status_code == 413


# ---------------------------------------------------------------------------
# GET /photo-packs/{id}/images
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pack_images():
    img1 = _mock_pack_image(img_id=1, url="/media/photo_packs/1/0_a.jpg", sort_order=0)
    img2 = _mock_pack_image(img_id=2, url="/media/photo_packs/1/1_b.jpg", sort_order=1)

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_mock_scalars([img1, img2]))

    app = _make_app(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/photo-packs/1/images")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert len(data["images"]) == 2
    assert data["images"][0]["id"] == 1
    assert data["images"][1]["sort_order"] == 1


@pytest.mark.asyncio
async def test_rename_pack_success():
    pack = _mock_pack(pack_id=5, name="Old Name")
    db = AsyncMock()
    db.get = AsyncMock(return_value=pack)
    db.commit = AsyncMock()

    app = _make_app(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.patch("/photo-packs/5", json={"name": "New Name"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["name"] == "New Name"
    assert pack.name == "New Name"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_rename_pack_empty_name():
    pack = _mock_pack(pack_id=5, name="Old Name")
    db = AsyncMock()
    db.get = AsyncMock(return_value=pack)

    app = _make_app(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.patch("/photo-packs/5", json={"name": "  "})
    assert resp.status_code == 400
    assert pack.name == "Old Name"


@pytest.mark.asyncio
async def test_rename_pack_not_found():
    db = AsyncMock()
    db.get = AsyncMock(return_value=None)

    app = _make_app(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.patch("/photo-packs/999", json={"name": "Test"})
    assert resp.status_code == 404
