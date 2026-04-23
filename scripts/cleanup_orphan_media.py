#!/usr/bin/env python3
"""
Standalone script + importable function for cleaning up orphan files in media/.

Orphan = file on disk not referenced by any product_images, photo_pack_images,
or listing_images row in the database.

Usage:
    python scripts/cleanup_orphan_media.py --dry-run   # default, show orphans
    python scripts/cleanup_orphan_media.py --apply      # actually delete
"""

from __future__ import annotations

import argparse
import asyncio
import os
import time
from dataclasses import dataclass, field

import structlog

log = structlog.get_logger("cleanup_orphan_media")

# Files that should never be deleted regardless of DB state
_PROTECTED_NAMES = frozenset({".gitignore", ".gitkeep", ".keep", "Thumbs.db", ".DS_Store"})

# Minimum file age (seconds) before it can be deleted — protects files being
# processed by yandex_download or image upload.
MIN_AGE_SECONDS = 86400  # 24 hours


@dataclass
class CleanupResult:
    total_files: int = 0
    referenced_files: int = 0
    orphan_files: int = 0
    skipped_young: int = 0
    skipped_protected: int = 0
    deleted_count: int = 0
    freed_bytes: int = 0
    errors: int = 0
    examples: list[str] = field(default_factory=list)


async def _get_referenced_paths(db) -> set[str]:
    """Query all image tables and return a set of relative paths under media/."""
    from sqlalchemy import select as sa_select

    from app.models.listing_image import ListingImage
    from app.models.photo_pack_image import PhotoPackImage
    from app.models.product_image import ProductImage

    referenced: set[str] = set()

    # product_images.url — format: /media/products/{id}/{file}
    rows = await db.execute(sa_select(ProductImage.url))
    for (url,) in rows:
        if url and url.startswith("/media/"):
            referenced.add(url[len("/media/"):])

    # photo_pack_images.url — format: /media/photo_packs/{id}/{file}
    rows = await db.execute(sa_select(PhotoPackImage.url))
    for (url,) in rows:
        if url and url.startswith("/media/"):
            referenced.add(url[len("/media/"):])

    # listing_images.file_path — format: /media/listings/{id}/{file}
    rows = await db.execute(sa_select(ListingImage.file_path))
    for (fp,) in rows:
        if fp and fp.startswith("/media/"):
            referenced.add(fp[len("/media/"):])

    return referenced


def _collect_disk_files(media_dir: str) -> list[tuple[str, str]]:
    """Walk media_dir and return list of (relative_path, absolute_path)."""
    result = []
    for dirpath, _dirnames, filenames in os.walk(media_dir):
        for fname in filenames:
            abs_path = os.path.join(dirpath, fname)
            rel_path = os.path.relpath(abs_path, media_dir)
            result.append((rel_path, abs_path))
    return result


async def cleanup_orphans(
    dry_run: bool = True,
    media_dir: str | None = None,
    db=None,
) -> CleanupResult:
    """Find and optionally delete orphan files in media/.

    Args:
        dry_run: If True (default), only report — don't delete.
        media_dir: Override media directory path. Defaults to settings.MEDIA_DIR.
        db: Optional SQLAlchemy AsyncSession. If None, creates one internally.

    Returns:
        CleanupResult with counts and examples.
    """
    from app.config import settings

    if media_dir is None:
        media_dir = settings.MEDIA_DIR

    media_dir = os.path.abspath(media_dir)
    if not os.path.isdir(media_dir):
        log.warning("media_dir_not_found", path=media_dir)
        return CleanupResult()

    # Get referenced paths from DB
    close_db = False
    if db is None:
        from app.db import async_session
        db = async_session()
        close_db = True

    try:
        referenced = await _get_referenced_paths(db)
    finally:
        if close_db:
            await db.close()

    # Collect files on disk
    disk_files = _collect_disk_files(media_dir)
    now = time.time()
    result = CleanupResult(total_files=len(disk_files))

    for rel_path, abs_path in disk_files:
        basename = os.path.basename(rel_path)

        # Skip protected files
        if basename in _PROTECTED_NAMES:
            result.skipped_protected += 1
            continue

        # Check if referenced in DB
        if rel_path in referenced:
            result.referenced_files += 1
            continue

        # Orphan found
        result.orphan_files += 1

        # Skip young files (< 24h)
        try:
            mtime = os.path.getmtime(abs_path)
        except OSError:
            continue
        age = now - mtime
        if age < MIN_AGE_SECONDS:
            result.skipped_young += 1
            if len(result.examples) < 20:
                result.examples.append(f"[young] {rel_path}")
            continue

        # Collect examples
        if len(result.examples) < 20:
            result.examples.append(rel_path)

        if not dry_run:
            try:
                size = os.path.getsize(abs_path)
                os.remove(abs_path)
                result.deleted_count += 1
                result.freed_bytes += size
            except OSError as exc:
                log.warning("delete_failed", path=abs_path, error=str(exc))
                result.errors += 1

    # Clean up empty directories after deletion
    if not dry_run and result.deleted_count > 0:
        _remove_empty_dirs(media_dir)

    return result


def _remove_empty_dirs(media_dir: str) -> None:
    """Remove empty subdirectories inside media_dir (bottom-up)."""
    for dirpath, dirnames, filenames in os.walk(media_dir, topdown=False):
        if dirpath == media_dir:
            continue
        if not dirnames and not filenames:
            try:
                os.rmdir(dirpath)
            except OSError:
                pass


def _print_result(result: CleanupResult, dry_run: bool) -> None:
    mode = "DRY-RUN" if dry_run else "APPLY"
    print(f"\n=== Orphan Media Cleanup [{mode}] ===")
    print(f"Total files on disk:   {result.total_files}")
    print(f"Referenced in DB:      {result.referenced_files}")
    print(f"Orphans found:         {result.orphan_files}")
    print(f"  Skipped (< 24h):     {result.skipped_young}")
    print(f"  Skipped (protected): {result.skipped_protected}")
    if not dry_run:
        print(f"  Deleted:             {result.deleted_count}")
        freed_mb = result.freed_bytes / 1024 / 1024
        print(f"  Freed:               {freed_mb:.1f} MB")
        if result.errors:
            print(f"  Errors:              {result.errors}")
    if result.examples:
        print(f"\nExamples (first {len(result.examples)}):")
        for p in result.examples:
            print(f"  {p}")
    print()


async def _main() -> None:
    parser = argparse.ArgumentParser(description="Clean up orphan files in media/")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true", default=True, help="Show orphans without deleting (default)")
    group.add_argument("--apply", action="store_true", help="Actually delete orphan files")
    args = parser.parse_args()

    dry_run = not args.apply

    result = await cleanup_orphans(dry_run=dry_run)
    _print_result(result, dry_run)

    log.info(
        "orphan_cleanup",
        dry_run=dry_run,
        total_files=result.total_files,
        orphan_files=result.orphan_files,
        deleted_count=result.deleted_count,
        freed_bytes=result.freed_bytes,
        skipped_young=result.skipped_young,
    )


if __name__ == "__main__":
    asyncio.run(_main())
