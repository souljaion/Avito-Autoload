import asyncio
import os
import shutil
from typing import List

import aiofiles
import structlog
from fastapi import APIRouter, Depends, Request, Form, UploadFile, File
from fastapi.responses import JSONResponse
from PIL import UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db import get_db
from app.models.photo_pack import PhotoPack
from app.models.photo_pack_image import PhotoPackImage
from app.services.image_processor import process_image_async, make_thumbnail_async
from app.utils.uploads import check_content_length

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/photo-packs", tags=["photo-packs"])


def _thumb_url(url: str) -> str:
    """Derive thumb URL from main URL: /media/.../0_foo.jpg -> /media/.../0_foo_thumb.jpg"""
    base, ext = os.path.splitext(url)
    return f"{base}_thumb{ext}"


@router.get("")
async def list_packs(
    model_id: int | None = None,
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(PhotoPack)
        .options(selectinload(PhotoPack.images))
        .order_by(PhotoPack.id.desc())
    )
    if model_id is not None:
        stmt = stmt.where(PhotoPack.model_id == model_id)
    result = await db.execute(stmt)
    packs = result.scalars().unique().all()
    return JSONResponse({
        "ok": True,
        "packs": [
            {
                "id": p.id,
                "name": p.name,
                "model_id": p.model_id,
                "image_count": len(p.images),
                "images": [
                    {
                        "id": img.id,
                        "url": img.url,
                        "thumb_url": _thumb_url(img.url),
                        "sort_order": img.sort_order,
                    }
                    for img in p.images
                ],
            }
            for p in packs
        ],
    })


@router.post("")
async def create_pack(
    request: Request,
    name: str = Form(...),
    model_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
):
    pack = PhotoPack(name=name, model_id=model_id)
    db.add(pack)
    await db.commit()
    return JSONResponse({"ok": True, "id": pack.id, "name": pack.name})


@router.patch("/{pack_id}")
async def rename_pack(pack_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    pack = await db.get(PhotoPack, pack_id)
    if not pack:
        return JSONResponse({"ok": False, "error": "Пак не найден"}, status_code=404)
    body = await request.json()
    name = (body.get("name") or "").strip()
    if not name or len(name) > 100:
        return JSONResponse({"ok": False, "error": "Имя должно быть от 1 до 100 символов"}, status_code=400)
    pack.name = name
    await db.commit()
    return JSONResponse({"ok": True, "id": pack.id, "name": pack.name})


async def _process_one_file(raw: bytes) -> tuple[bytes, bytes]:
    """Process main image + thumbnail in threadpool. Returns (main_data, thumb_data)."""
    main_data = await process_image_async(raw, max_side=1200, quality=82)
    thumb_data = await make_thumbnail_async(main_data, max_side=300, quality=70)
    return main_data, thumb_data


@router.post("/{pack_id}/upload")
async def upload_photos(
    request: Request,
    pack_id: int,
    files: List[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
):
    check_content_length(request)
    pack = await db.get(PhotoPack, pack_id)
    if not pack:
        return JSONResponse({"ok": False, "error": "Пак не найден"}, status_code=404)

    pack_dir = os.path.join(settings.MEDIA_DIR, "photo_packs", str(pack_id))
    os.makedirs(pack_dir, exist_ok=True)

    result = await db.execute(
        select(PhotoPackImage)
        .where(PhotoPackImage.pack_id == pack_id)
        .order_by(PhotoPackImage.sort_order.desc())
    )
    existing = result.scalars().all()
    max_order = existing[0].sort_order if existing else -1

    MAX_UPLOAD_SIZE = 20 * 1024 * 1024  # 20 MB per file

    # Read all files first with size check
    raw_files: list[tuple[int, str, bytes]] = []
    for i, file in enumerate(files):
        if not file.filename:
            continue
        raw = await file.read()
        if len(raw) > MAX_UPLOAD_SIZE:
            return JSONResponse({"ok": False, "error": f"Файл {file.filename} превышает 20 МБ"}, status_code=413)
        raw_files.append((i, file.filename, raw))

    # Process all images in parallel via threadpool
    async def _safe_process(idx: int, filename: str, raw: bytes):
        try:
            main_data, thumb_data = await _process_one_file(raw)
            return idx, filename, main_data, thumb_data, None
        except (ValueError, OSError, UnidentifiedImageError) as exc:
            return idx, filename, None, None, str(exc)

    tasks = [_safe_process(idx, fn, raw) for idx, fn, raw in raw_files]
    results = await asyncio.gather(*tasks)

    # Save results to disk and DB (must be sequential for ordering/DB)
    uploaded = []
    for idx, filename, main_data, thumb_data, error in sorted(results, key=lambda r: r[0]):
        if error:
            uploaded.append({"filename": filename, "error": error})
            continue

        base = os.path.splitext(filename or "image")[0]
        clean_name = f"{base}.jpg"
        order = max_order + 1 + idx
        fname = f"{order}_{clean_name}"
        thumb_name = f"{order}_{base}_thumb.jpg"

        filepath = os.path.join(pack_dir, fname)
        thumb_path = os.path.join(pack_dir, thumb_name)

        async with aiofiles.open(filepath, "wb") as f:
            await f.write(main_data)
        async with aiofiles.open(thumb_path, "wb") as f:
            await f.write(thumb_data)

        url = f"/media/photo_packs/{pack_id}/{fname}"
        thumb_url_str = f"/media/photo_packs/{pack_id}/{thumb_name}"

        img_record = PhotoPackImage(
            pack_id=pack_id,
            file_path=filepath,
            url=url,
            sort_order=order,
        )
        db.add(img_record)
        await db.flush()
        uploaded.append({"id": img_record.id, "url": url, "thumb_url": thumb_url_str, "filename": fname})

    await db.commit()
    logger.info("pack upload complete", pack_id=pack_id, total=len(raw_files),
                ok=sum(1 for u in uploaded if "id" in u),
                errors=sum(1 for u in uploaded if "error" in u))
    return JSONResponse({"ok": True, "images": uploaded})


@router.delete("/{pack_id}")
async def delete_pack(pack_id: int, db: AsyncSession = Depends(get_db)):
    pack = await db.get(PhotoPack, pack_id)
    if not pack:
        return JSONResponse({"ok": False, "error": "Пак не найден"}, status_code=404)

    pack_dir = os.path.join(settings.MEDIA_DIR, "photo_packs", str(pack_id))
    if os.path.isdir(pack_dir):
        shutil.rmtree(pack_dir)

    await db.delete(pack)
    await db.commit()
    return JSONResponse({"ok": True})


@router.get("/{pack_id}/images")
async def pack_images(pack_id: int, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(PhotoPackImage)
        .where(PhotoPackImage.pack_id == pack_id)
        .order_by(PhotoPackImage.sort_order)
    )
    result = await db.execute(stmt)
    images = result.scalars().all()
    return JSONResponse({
        "ok": True,
        "images": [
            {
                "id": img.id,
                "url": img.url,
                "thumb_url": _thumb_url(img.url),
                "sort_order": img.sort_order,
                "download_status": img.download_status,
                "download_error": img.download_error,
                "yandex_file_path": img.yandex_file_path,
                "source_type": img.source_type,
            }
            for img in images
        ],
    })
