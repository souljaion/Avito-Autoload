"""Tests for listings routes: list, counts, create, edit, patch, delete."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from app.db import get_db
from app.routes.listings import router


def _make_app(mock_db):
    app = FastAPI()
    app.include_router(router)

    async def override_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_db
    return app


def _make_product(pid=1, title="Test Sneakers", price=5000, brand="Nike", status="draft"):
    p = MagicMock()
    p.id = pid
    p.title = title
    p.price = price
    p.brand = brand
    p.color = "black"
    p.status = status
    p.avito_id = None
    p.description = "test description"
    p.images = []
    return p


def _make_account(acc_id=1, name="TestAcc"):
    a = MagicMock()
    a.id = acc_id
    a.name = name
    return a


def _make_listing(
    lid=1, product_id=1, account_id=1, status="draft",
    scheduled_at=None, published_at=None, avito_id=None,
    product=None, account=None, images=None,
):
    ls = MagicMock()
    ls.id = lid
    ls.product_id = product_id
    ls.account_id = account_id
    ls.status = status
    ls.scheduled_at = scheduled_at
    ls.published_at = published_at
    ls.avito_id = avito_id
    ls.updated_at = datetime(2026, 4, 15, 12, 0, 0)
    ls.product = product or _make_product(pid=product_id)
    ls.account = account or _make_account(acc_id=account_id)
    ls.images = images if images is not None else []
    return ls


def _make_listing_image(img_id=1, listing_id=1, file_path="/media/listings/1/0_img.jpg", order=0):
    img = MagicMock()
    img.id = img_id
    img.listing_id = listing_id
    img.file_path = file_path
    img.order = order
    return img


# ── GET /api/listings ──


class TestListListings:
    @pytest.mark.asyncio
    async def test_list_listings_empty(self):
        """Empty listings should return empty items list with pagination."""
        count_result = MagicMock()
        count_result.scalar.return_value = 0

        listings_result = MagicMock()
        listings_result.scalars.return_value.all.return_value = []

        call_idx = [0]

        async def mock_execute(stmt, *args, **kwargs):
            call_idx[0] += 1
            if call_idx[0] == 1:
                return count_result
            return listings_result

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=mock_execute)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/listings")

        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["total_pages"] == 1
        assert data["has_more"] is False

    @pytest.mark.asyncio
    async def test_list_listings_with_results(self):
        """Should return serialized listing items."""
        listing = _make_listing(lid=10, status="draft")

        count_result = MagicMock()
        count_result.scalar.return_value = 1

        listings_result = MagicMock()
        listings_result.scalars.return_value.all.return_value = [listing]

        call_idx = [0]

        async def mock_execute(stmt, *args, **kwargs):
            call_idx[0] += 1
            if call_idx[0] == 1:
                return count_result
            return listings_result

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=mock_execute)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/listings")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1
        item = data["items"][0]
        assert item["id"] == 10
        assert item["title"] == "Test Sneakers"
        assert item["status"] == "draft"
        assert item["account"] == "TestAcc"
        assert item["image_count"] == 0

    @pytest.mark.asyncio
    async def test_list_listings_with_listing_images(self):
        """Listing with images should return first image by order."""
        img1 = _make_listing_image(img_id=1, order=2, file_path="/media/listings/1/2_img.jpg")
        img2 = _make_listing_image(img_id=2, order=0, file_path="/media/listings/1/0_img.jpg")
        listing = _make_listing(lid=1, images=[img1, img2])

        count_result = MagicMock()
        count_result.scalar.return_value = 1

        listings_result = MagicMock()
        listings_result.scalars.return_value.all.return_value = [listing]

        call_idx = [0]

        async def mock_execute(stmt, *args, **kwargs):
            call_idx[0] += 1
            if call_idx[0] == 1:
                return count_result
            return listings_result

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=mock_execute)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/listings")

        data = resp.json()
        # Should pick image with order=0 (sorted first)
        assert data["items"][0]["image"] == "/media/listings/1/0_img.jpg"
        assert data["items"][0]["image_count"] == 2

    @pytest.mark.asyncio
    async def test_list_listings_pagination(self):
        """Per_page should be capped at 200."""
        count_result = MagicMock()
        count_result.scalar.return_value = 0

        listings_result = MagicMock()
        listings_result.scalars.return_value.all.return_value = []

        call_idx = [0]

        async def mock_execute(stmt, *args, **kwargs):
            call_idx[0] += 1
            if call_idx[0] == 1:
                return count_result
            return listings_result

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=mock_execute)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/listings?per_page=500&page=2")

        data = resp.json()
        # per_page capped to 200
        assert data["per_page"] == 200


# ── GET /api/listings/counts ──


class TestListingsCounts:
    @pytest.mark.asyncio
    async def test_counts_returns_grouped(self):
        """Should return counts grouped by product status."""
        result = MagicMock()
        result.all.return_value = [("draft", 5), ("active", 3)]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=result)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/listings/counts")

        assert resp.status_code == 200
        data = resp.json()
        assert data["draft"] == 5
        assert data["active"] == 3
        assert data["scheduled"] == 0
        assert data["all"] == 8

    @pytest.mark.asyncio
    async def test_counts_empty(self):
        """Empty table should return all zeros."""
        result = MagicMock()
        result.all.return_value = []

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=result)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/listings/counts")

        data = resp.json()
        assert data == {"draft": 0, "scheduled": 0, "active": 0, "all": 0}


# ── POST /products/{product_id}/listings ──


class TestCreateListing:
    @pytest.mark.asyncio
    async def test_create_listing_missing_account_id(self):
        """Missing account_id should return 400."""
        mock_db = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/products/1/listings", json={})

        assert resp.status_code == 400
        assert resp.json()["ok"] is False

    @pytest.mark.asyncio
    async def test_create_listing_product_not_found(self):
        """Nonexistent product should return 404."""
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/products/999/listings", json={"account_id": 1})

        assert resp.status_code == 404
        assert resp.json()["ok"] is False

    @pytest.mark.asyncio
    async def test_create_listing_success(self):
        """Successful creation should return ok with id."""
        product = _make_product(pid=1)
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=product)
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()

        # After db.add, the listing.id gets set by the ORM;
        # simulate this by patching Listing constructor
        app = _make_app(mock_db)

        with patch("app.routes.listings.Listing") as MockListing:
            new_listing = MagicMock()
            new_listing.id = 42
            new_listing.status = "draft"
            MockListing.return_value = new_listing

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/products/1/listings", json={"account_id": 1})

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["id"] == 42
        mock_db.add.assert_called_once_with(new_listing)
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_listing_with_scheduled_at(self):
        """Providing scheduled_at should set status to 'scheduled'."""
        product = _make_product(pid=1)
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=product)
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        with patch("app.routes.listings.Listing") as MockListing:
            new_listing = MagicMock()
            new_listing.id = 43
            MockListing.return_value = new_listing

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/products/1/listings",
                    json={"account_id": 1, "scheduled_at": "2026-04-20T10:00:00"},
                )

        assert resp.status_code == 200
        # Verify Listing was constructed with status="scheduled"
        call_kwargs = MockListing.call_args[1]
        assert call_kwargs["status"] == "scheduled"
        assert call_kwargs["scheduled_at"] is not None


# ── PATCH /listings/{id} ──


class TestPatchListing:
    @pytest.mark.asyncio
    async def test_patch_listing_not_found(self):
        """Patching nonexistent listing should return 404."""
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch("/listings/999", json={"status": "active"})

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_patch_listing_update_status(self):
        """Should update status and return ok."""
        listing = _make_listing(lid=5, status="draft")
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=listing)
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch("/listings/5", json={"status": "active"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["id"] == 5
        assert listing.status == "active"

    @pytest.mark.asyncio
    async def test_patch_listing_update_account_id(self):
        """Should update account_id."""
        listing = _make_listing(lid=5, account_id=1)
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=listing)
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch("/listings/5", json={"account_id": 2})

        assert resp.status_code == 200
        assert listing.account_id == 2

    @pytest.mark.asyncio
    async def test_patch_listing_clear_scheduled_at(self):
        """Sending scheduled_at=None should clear it."""
        listing = _make_listing(lid=5, scheduled_at=datetime(2026, 5, 1))
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=listing)
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch("/listings/5", json={"scheduled_at": None})

        assert resp.status_code == 200
        assert listing.scheduled_at is None


# ── DELETE /listings/{id} ──


class TestDeleteListing:
    @pytest.mark.asyncio
    async def test_delete_listing_not_found(self):
        """Deleting nonexistent listing should return 404."""
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.delete("/listings/999")

        assert resp.status_code == 404
        assert resp.json()["ok"] is False

    @pytest.mark.asyncio
    async def test_delete_listing_success(self):
        """Deleting existing listing should remove it and return ok."""
        listing = _make_listing(lid=7)
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=listing)
        mock_db.delete = AsyncMock()
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        with patch("app.routes.listings.os.path.isdir", return_value=False):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.delete("/listings/7")

        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        mock_db.delete.assert_called_once_with(listing)
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_listing_removes_media_dir(self):
        """Delete should also remove the media directory if it exists."""
        listing = _make_listing(lid=7)
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=listing)
        mock_db.delete = AsyncMock()
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        with patch("app.routes.listings.os.path.isdir", return_value=True) as mock_isdir, \
             patch("app.routes.listings.shutil.rmtree") as mock_rmtree:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.delete("/listings/7")

        assert resp.status_code == 200
        mock_rmtree.assert_called_once()


# ── POST /listings/{id}/images/{image_id}/delete ──


class TestDeleteListingImage:
    @pytest.mark.asyncio
    async def test_delete_image_success(self):
        """Should delete the image record and file, return ok."""
        img = _make_listing_image(img_id=10, listing_id=3, file_path="/media/listings/3/0_img.jpg")
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=img)
        mock_db.delete = AsyncMock()
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        with patch("app.routes.listings.os.path.normpath", side_effect=lambda x: x), \
             patch("app.routes.listings.os.path.exists", return_value=True), \
             patch("app.routes.listings.os.remove") as mock_remove:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/listings/3/images/10/delete",
                    headers={"accept": "application/json"},
                )

        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        mock_db.delete.assert_called_once_with(img)
        mock_remove.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_image_wrong_listing_id(self):
        """Image belonging to different listing should not be deleted."""
        img = _make_listing_image(img_id=10, listing_id=99)
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=img)
        mock_db.delete = AsyncMock()
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/listings/3/images/10/delete",
                headers={"accept": "application/json"},
            )

        assert resp.status_code == 200
        # Image not deleted because listing_id mismatch
        mock_db.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_image_not_found(self):
        """Nonexistent image should still return ok (no error)."""
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/listings/3/images/999/delete",
                headers={"accept": "application/json"},
            )

        assert resp.status_code == 200
        assert resp.json()["ok"] is True


# ── GET /listings/{id}/edit ──


class TestEditListingPage:
    @pytest.mark.asyncio
    async def test_edit_page_not_found(self):
        """Nonexistent listing should return 404 HTML."""
        listing_result = MagicMock()
        listing_result.scalar_one_or_none.return_value = None

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=listing_result)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/listings/999/edit")

        assert resp.status_code == 404


# ── POST /listings/{id}/edit (form update) ──


class TestUpdateListingForm:
    @pytest.mark.asyncio
    async def test_form_update_not_found(self):
        """Nonexistent listing should return 404."""
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=result_mock)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/listings/999/edit",
                data={"title": "New Title"},
                follow_redirects=False,
            )

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_form_update_success_redirects(self):
        """Successful form update should redirect to edit page."""
        product = _make_product(pid=1)
        listing = _make_listing(lid=5, product=product, status="draft")

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = listing

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=result_mock)
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/listings/5/edit",
                data={
                    "title": "Updated Title",
                    "description": "Updated desc",
                    "price": "7000",
                    "brand": "Adidas",
                    "color": "white",
                    "status": "draft",
                    "account_id": "2",
                    "scheduled_at": "",
                },
                follow_redirects=False,
            )

        assert resp.status_code == 303
        assert "/listings/5/edit" in resp.headers.get("location", "")
        # Verify product fields were updated
        assert product.title == "Updated Title"
        assert product.price == 7000
        assert product.brand == "Adidas"
        assert listing.account_id == 2

    @pytest.mark.asyncio
    async def test_form_update_with_scheduled_at(self):
        """Setting scheduled_at should change status to scheduled."""
        product = _make_product(pid=1)
        listing = _make_listing(lid=5, product=product, status="draft")

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = listing

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=result_mock)
        mock_db.commit = AsyncMock()
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/listings/5/edit",
                data={
                    "title": "Scheduled",
                    "status": "draft",
                    "scheduled_at": "2026-05-01T10:00:00",
                },
                follow_redirects=False,
            )

        assert resp.status_code == 303
        assert listing.status == "scheduled"
        assert listing.scheduled_at is not None


# ── POST /listings/{id}/images (upload) ──


class TestUploadListingImages:
    @pytest.mark.asyncio
    async def test_upload_listing_not_found_json(self):
        """Uploading to nonexistent listing should return 404 JSON."""
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/listings/999/images",
                files=[("files", ("test.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 100, "image/jpeg"))],
                headers={"accept": "application/json"},
            )

        assert resp.status_code == 404
        assert resp.json()["ok"] is False

    @pytest.mark.asyncio
    async def test_upload_listing_not_found_redirect(self):
        """Uploading to nonexistent listing without JSON accept should redirect."""
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/listings/999/images",
                files=[("files", ("test.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 100, "image/jpeg"))],
                follow_redirects=False,
            )

        assert resp.status_code == 303

    @pytest.mark.asyncio
    async def test_upload_file_too_large_json(self):
        """File exceeding 20 MB should return 413."""
        listing = _make_listing(lid=1)
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=listing)
        app = _make_app(mock_db)

        big_data = b"\x00" * (21 * 1024 * 1024)  # 21 MB

        with patch("app.routes.listings.os.makedirs"):
            # Mock the existing images query
            existing_result = MagicMock()
            existing_result.scalars.return_value.all.return_value = []
            mock_db.execute = AsyncMock(return_value=existing_result)

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/listings/1/images",
                    files=[("files", ("huge.jpg", big_data, "image/jpeg"))],
                    headers={"accept": "application/json"},
                )

        assert resp.status_code == 413

    @pytest.mark.asyncio
    async def test_upload_success(self):
        """Successful upload should process images and return uploaded list."""
        listing = _make_listing(lid=5)
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=listing)
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()

        existing_result = MagicMock()
        existing_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=existing_result)

        app = _make_app(mock_db)

        fake_jpeg = b"\xff\xd8\xff\xe0processed"

        with patch("app.routes.listings.os.makedirs"), \
             patch("app.routes.listings.process_image_async", new_callable=AsyncMock, return_value=fake_jpeg), \
             patch("app.routes.listings.aiofiles.open", create=True) as mock_aio:
            # Mock aiofiles context manager
            mock_file = AsyncMock()
            mock_aio.return_value.__aenter__ = AsyncMock(return_value=mock_file)
            mock_aio.return_value.__aexit__ = AsyncMock(return_value=False)

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/listings/5/images",
                    files=[("files", ("photo.jpg", b"\xff\xd8\xff\xe0raw", "image/jpeg"))],
                    headers={"accept": "application/json"},
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert len(data["images"]) == 1
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_upload_skips_errored_files(self):
        """Files that fail image processing should be skipped."""
        listing = _make_listing(lid=5)
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=listing)
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()

        existing_result = MagicMock()
        existing_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=existing_result)

        app = _make_app(mock_db)

        async def failing_process(*args, **kwargs):
            raise ValueError("Bad image")

        with patch("app.routes.listings.os.makedirs"), \
             patch("app.routes.listings.process_image_async", side_effect=failing_process):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/listings/5/images",
                    files=[("files", ("bad.jpg", b"\x00\x00\x00", "image/jpeg"))],
                    headers={"accept": "application/json"},
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert len(data["images"]) == 0
