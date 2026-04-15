"""Unit tests for app/routes/images.py"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.db import get_db
from app.routes.images import router


def _make_app(mock_db):
    app = FastAPI()
    app.include_router(router)

    async def override_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_db
    return app


def _mock_product(product_id=1):
    p = MagicMock()
    p.id = product_id
    return p


def _mock_product_image(img_id=1, product_id=1, url="/media/products/1/0_shoe.jpg",
                        filename="0_shoe.jpg", sort_order=0, is_main=False):
    img = MagicMock()
    img.id = img_id
    img.product_id = product_id
    img.url = url
    img.filename = filename
    img.sort_order = sort_order
    img.is_main = is_main
    return img


def _mock_scalars(items):
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = items
    result = MagicMock()
    result.scalars.return_value = scalars_mock
    return result


# ---------------------------------------------------------------------------
# POST /products/{id}/images  (upload)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upload_images_product_not_found_json():
    db = AsyncMock()
    db.get = AsyncMock(return_value=None)

    app = _make_app(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            "/products/999/images",
            files=[("files", ("test.jpg", b"fake", "image/jpeg"))],
            headers={"accept": "application/json"},
        )
    assert resp.status_code == 404
    assert resp.json()["ok"] is False


@pytest.mark.asyncio
async def test_upload_images_product_not_found_redirect():
    db = AsyncMock()
    db.get = AsyncMock(return_value=None)

    app = _make_app(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test",
                           follow_redirects=False) as ac:
        resp = await ac.post(
            "/products/999/images",
            files=[("files", ("test.jpg", b"fake", "image/jpeg"))],
            headers={"accept": "text/html"},
        )
    assert resp.status_code == 303
    assert "/products" in resp.headers["location"]


@pytest.mark.asyncio
async def test_upload_images_too_large_json():
    product = _mock_product(product_id=1)
    db = AsyncMock()
    db.get = AsyncMock(return_value=product)
    db.execute = AsyncMock(return_value=_mock_scalars([]))

    app = _make_app(db)
    big_data = b"x" * (21 * 1024 * 1024)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            "/products/1/images",
            files=[("files", ("big.jpg", big_data, "image/jpeg"))],
            headers={"accept": "application/json"},
        )
    assert resp.status_code == 413


@pytest.mark.asyncio
async def test_upload_images_too_large_redirect():
    product = _mock_product(product_id=1)
    db = AsyncMock()
    db.get = AsyncMock(return_value=product)
    db.execute = AsyncMock(return_value=_mock_scalars([]))

    app = _make_app(db)
    big_data = b"x" * (21 * 1024 * 1024)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test",
                           follow_redirects=False) as ac:
        resp = await ac.post(
            "/products/1/images",
            files=[("files", ("big.jpg", big_data, "image/jpeg"))],
            headers={"accept": "text/html"},
        )
    assert resp.status_code == 303
    assert "error=" in resp.headers["location"]


@pytest.mark.asyncio
@patch("app.routes.images.aiofiles.open")
@patch("app.routes.images.os.makedirs")
@patch("app.routes.images.process_image_async", new_callable=AsyncMock)
async def test_upload_images_success_json(mock_process, mock_makedirs, mock_aio_open):
    mock_process.return_value = b"processed_jpeg_bytes"

    file_mock = AsyncMock()
    file_mock.write = AsyncMock()
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=file_mock)
    cm.__aexit__ = AsyncMock(return_value=False)
    mock_aio_open.return_value = cm

    product = _mock_product(product_id=1)
    db = AsyncMock()
    db.get = AsyncMock(return_value=product)
    db.execute = AsyncMock(return_value=_mock_scalars([]))  # no existing images
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    app = _make_app(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            "/products/1/images",
            files=[("files", ("shoe.jpg", b"fake_image", "image/jpeg"))],
            headers={"accept": "application/json"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert len(data["images"]) == 1
    assert data["images"][0]["is_main"] is True  # first image becomes main


@pytest.mark.asyncio
@patch("app.routes.images.aiofiles.open")
@patch("app.routes.images.os.makedirs")
@patch("app.routes.images.process_image_async", new_callable=AsyncMock)
async def test_upload_images_existing_main_not_overridden(mock_process, mock_makedirs, mock_aio_open):
    """When existing images have a main, new upload should not set is_main."""
    mock_process.return_value = b"processed"

    file_mock = AsyncMock()
    file_mock.write = AsyncMock()
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=file_mock)
    cm.__aexit__ = AsyncMock(return_value=False)
    mock_aio_open.return_value = cm

    existing_img = _mock_product_image(img_id=10, is_main=True, sort_order=0)
    product = _mock_product(product_id=1)
    db = AsyncMock()
    db.get = AsyncMock(return_value=product)
    db.execute = AsyncMock(return_value=_mock_scalars([existing_img]))
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    app = _make_app(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            "/products/1/images",
            files=[("files", ("new.jpg", b"fake_image", "image/jpeg"))],
            headers={"accept": "application/json"},
        )
    data = resp.json()
    assert data["ok"] is True
    # New image should NOT be main since existing main exists
    assert data["images"][0]["is_main"] is False


@pytest.mark.asyncio
@patch("app.routes.images.aiofiles.open")
@patch("app.routes.images.os.makedirs")
@patch("app.routes.images.process_image_async", new_callable=AsyncMock)
async def test_upload_images_redirect_on_html(mock_process, mock_makedirs, mock_aio_open):
    mock_process.return_value = b"processed"

    file_mock = AsyncMock()
    file_mock.write = AsyncMock()
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=file_mock)
    cm.__aexit__ = AsyncMock(return_value=False)
    mock_aio_open.return_value = cm

    product = _mock_product(product_id=1)
    db = AsyncMock()
    db.get = AsyncMock(return_value=product)
    db.execute = AsyncMock(return_value=_mock_scalars([]))
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    app = _make_app(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test",
                           follow_redirects=False) as ac:
        resp = await ac.post(
            "/products/1/images",
            files=[("files", ("shoe.jpg", b"fake", "image/jpeg"))],
            headers={"accept": "text/html"},
        )
    assert resp.status_code == 303
    assert "/products/1" in resp.headers["location"]


# ---------------------------------------------------------------------------
# POST /products/{id}/images/{img_id}/main
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_set_main_image():
    img1 = _mock_product_image(img_id=1, is_main=True)
    img2 = _mock_product_image(img_id=2, is_main=False)

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_mock_scalars([img1, img2]))
    db.commit = AsyncMock()

    app = _make_app(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test",
                           follow_redirects=False) as ac:
        resp = await ac.post("/products/1/images/2/main")
    assert resp.status_code == 303
    # img2 should now be main, img1 should not
    assert img2.is_main is True
    assert img1.is_main is False


# ---------------------------------------------------------------------------
# POST /products/{id}/images/{img_id}/delete
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch("app.routes.images.os.remove")
@patch("app.routes.images.os.path.exists", return_value=True)
async def test_delete_image_json(mock_exists, mock_remove):
    img = _mock_product_image(img_id=5, product_id=1, filename="0_shoe.jpg")
    db = AsyncMock()
    db.get = AsyncMock(return_value=img)
    db.delete = AsyncMock()
    db.commit = AsyncMock()

    app = _make_app(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            "/products/1/images/5/delete",
            headers={"accept": "application/json"},
        )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    db.delete.assert_awaited_once_with(img)
    mock_remove.assert_called_once()


@pytest.mark.asyncio
async def test_delete_image_not_found_json():
    db = AsyncMock()
    db.get = AsyncMock(return_value=None)

    app = _make_app(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            "/products/1/images/999/delete",
            headers={"accept": "application/json"},
        )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True  # returns ok even if not found


@pytest.mark.asyncio
async def test_delete_image_wrong_product_id():
    """Image belongs to product 2 but request says product 1 => no deletion."""
    img = _mock_product_image(img_id=5, product_id=2)
    db = AsyncMock()
    db.get = AsyncMock(return_value=img)
    db.commit = AsyncMock()

    app = _make_app(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            "/products/1/images/5/delete",
            headers={"accept": "application/json"},
        )
    assert resp.status_code == 200
    # delete should NOT have been called
    db.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_image_redirect_on_html():
    db = AsyncMock()
    db.get = AsyncMock(return_value=None)

    app = _make_app(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test",
                           follow_redirects=False) as ac:
        resp = await ac.post(
            "/products/1/images/5/delete",
            headers={"accept": "text/html"},
        )
    assert resp.status_code == 303
    assert "/products/1" in resp.headers["location"]
