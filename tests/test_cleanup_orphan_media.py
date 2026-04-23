"""Tests for orphan media cleanup."""

import os
import time

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product_image import ProductImage
from app.models.photo_pack_image import PhotoPackImage
from app.models.product import Product
from app.models.photo_pack import PhotoPack
from app.models.model import Model
from scripts.cleanup_orphan_media import cleanup_orphans, CleanupResult, MIN_AGE_SECONDS


@pytest_asyncio.fixture(autouse=True)
async def _reset_pool():
    """Dispose the shared engine pool between tests to avoid stale connections."""
    from app.db import engine
    yield
    await engine.dispose()


@pytest.fixture
def media_dir(tmp_path):
    """Create a temporary media directory with subdirectories."""
    media = tmp_path / "media"
    (media / "products" / "1").mkdir(parents=True)
    (media / "products" / "2").mkdir(parents=True)
    (media / "photo_packs" / "10").mkdir(parents=True)
    (media / "listings").mkdir(parents=True)
    return str(media)


def _create_file(media_dir: str, rel_path: str, content: bytes = b"x" * 1024, age_hours: float = 48) -> str:
    """Create a file and set its mtime to `age_hours` ago."""
    abs_path = os.path.join(media_dir, rel_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    with open(abs_path, "wb") as f:
        f.write(content)
    old_time = time.time() - age_hours * 3600
    os.utime(abs_path, (old_time, old_time))
    return abs_path


@pytest.mark.asyncio
async def test_dry_run_does_not_delete(db: AsyncSession, media_dir: str):
    """Dry-run should report orphans but not delete any files."""
    # Create orphan files (old enough to be eligible)
    _create_file(media_dir, "products/99/0_orphan.jpg", age_hours=48)
    _create_file(media_dir, "photo_packs/99/0_orphan.jpg", age_hours=48)

    result = await cleanup_orphans(dry_run=True, media_dir=media_dir, db=db)

    assert result.orphan_files == 2
    assert result.deleted_count == 0
    # Files still exist
    assert os.path.exists(os.path.join(media_dir, "products/99/0_orphan.jpg"))
    assert os.path.exists(os.path.join(media_dir, "photo_packs/99/0_orphan.jpg"))


@pytest.mark.asyncio
async def test_apply_deletes_orphans(db: AsyncSession, media_dir: str):
    """Apply mode should delete orphan files and report freed bytes."""
    content = b"x" * 2048
    _create_file(media_dir, "products/99/0_orphan.jpg", content=content, age_hours=48)
    _create_file(media_dir, "photo_packs/99/0_orphan.jpg", content=content, age_hours=48)

    result = await cleanup_orphans(dry_run=False, media_dir=media_dir, db=db)

    assert result.deleted_count == 2
    assert result.freed_bytes == 2048 * 2
    assert not os.path.exists(os.path.join(media_dir, "products/99/0_orphan.jpg"))
    assert not os.path.exists(os.path.join(media_dir, "photo_packs/99/0_orphan.jpg"))


@pytest.mark.asyncio
async def test_young_files_not_deleted(db: AsyncSession, media_dir: str):
    """Files younger than 24 hours should not be deleted even with --apply."""
    # Create a file that's only 1 hour old
    _create_file(media_dir, "products/99/0_fresh.jpg", age_hours=1)
    # Create a file that's 48 hours old
    _create_file(media_dir, "products/99/1_old.jpg", age_hours=48)

    result = await cleanup_orphans(dry_run=False, media_dir=media_dir, db=db)

    assert result.skipped_young == 1
    assert result.deleted_count == 1
    # Fresh file still exists
    assert os.path.exists(os.path.join(media_dir, "products/99/0_fresh.jpg"))
    # Old file deleted
    assert not os.path.exists(os.path.join(media_dir, "products/99/1_old.jpg"))


@pytest.mark.asyncio
async def test_referenced_files_not_deleted(db: AsyncSession, media_dir: str):
    """Files referenced by product_images or photo_pack_images must not be deleted."""
    # Create a product with an image in DB
    product = Product(
        title="Test Product",
        status="active",
        category="Одежда, обувь, аксессуары",
        goods_type="Мужская обувь",
        price=1000,
        account_id=1,
    )
    db.add(product)
    await db.flush()

    img = ProductImage(
        product_id=product.id,
        url=f"/media/products/{product.id}/0_shoe.jpg",
        filename="0_shoe.jpg",
    )
    db.add(img)
    await db.flush()

    # Create a model + photo pack with an image in DB
    model = Model(name="Test Model")
    db.add(model)
    await db.flush()

    pack = PhotoPack(model_id=model.id, name="Pack 1")
    db.add(pack)
    await db.flush()

    pack_img = PhotoPackImage(
        pack_id=pack.id,
        file_path=f"/media/photo_packs/{pack.id}/0_pack.jpg",
        url=f"/media/photo_packs/{pack.id}/0_pack.jpg",
    )
    db.add(pack_img)
    await db.flush()

    # Create corresponding files on disk (old enough)
    _create_file(media_dir, f"products/{product.id}/0_shoe.jpg", age_hours=48)
    _create_file(media_dir, f"photo_packs/{pack.id}/0_pack.jpg", age_hours=48)
    # Also create an orphan
    _create_file(media_dir, "products/9999/0_orphan.jpg", age_hours=48)

    result = await cleanup_orphans(dry_run=False, media_dir=media_dir, db=db)

    assert result.referenced_files == 2
    assert result.deleted_count == 1
    # Referenced files still exist
    assert os.path.exists(os.path.join(media_dir, f"products/{product.id}/0_shoe.jpg"))
    assert os.path.exists(os.path.join(media_dir, f"photo_packs/{pack.id}/0_pack.jpg"))


@pytest.mark.asyncio
async def test_protected_files_not_deleted(db: AsyncSession, media_dir: str):
    """Service files like .gitkeep should never be deleted."""
    _create_file(media_dir, "products/.gitkeep", age_hours=48)
    _create_file(media_dir, "listings/.gitignore", age_hours=48)
    _create_file(media_dir, "products/99/0_orphan.jpg", age_hours=48)

    result = await cleanup_orphans(dry_run=False, media_dir=media_dir, db=db)

    assert result.skipped_protected == 2
    assert result.deleted_count == 1
    assert os.path.exists(os.path.join(media_dir, "products/.gitkeep"))
    assert os.path.exists(os.path.join(media_dir, "listings/.gitignore"))


@pytest.mark.asyncio
async def test_empty_media_dir(db: AsyncSession, tmp_path):
    """No files on disk should produce a clean zero result."""
    empty_dir = str(tmp_path / "empty_media")
    os.makedirs(empty_dir)

    result = await cleanup_orphans(dry_run=True, media_dir=empty_dir, db=db)

    assert result.total_files == 0
    assert result.orphan_files == 0


@pytest.mark.asyncio
async def test_empty_dirs_cleaned_after_apply(db: AsyncSession, media_dir: str):
    """After deleting all files in a subdirectory, the empty dir should be removed."""
    _create_file(media_dir, "products/9999/0_orphan.jpg", age_hours=48)

    result = await cleanup_orphans(dry_run=False, media_dir=media_dir, db=db)

    assert result.deleted_count == 1
    # The products/9999/ directory should be cleaned up
    assert not os.path.isdir(os.path.join(media_dir, "products/9999"))
    # But products/ itself should remain
    assert os.path.isdir(os.path.join(media_dir, "products"))
