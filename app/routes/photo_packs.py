import os
import shutil
from typing import List

import aiofiles
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
from app.services.image_processor import process_image, make_thumbnail

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


@router.post("/{pack_id}/upload")
async def upload_photos(
    pack_id: int,
    files: List[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
):
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

    uploaded = []
    for i, file in enumerate(files):
        if not file.filename:
            continue
        try:
            raw = await file.read()
            main_data = process_image(raw, max_side=1200, quality=82)
            thumb_data = make_thumbnail(main_data, max_side=300, quality=70)
        except (ValueError, OSError, UnidentifiedImageError) as exc:
            uploaded.append({"filename": file.filename, "error": str(exc)})
            continue

        base = os.path.splitext(file.filename or "image")[0]
        clean_name = f"{base}.jpg"
        order = max_order + 1 + i
        filename = f"{order}_{clean_name}"
        thumb_name = f"{order}_{base}_thumb.jpg"

        filepath = os.path.join(pack_dir, filename)
        thumb_path = os.path.join(pack_dir, thumb_name)

        async with aiofiles.open(filepath, "wb") as f:
            await f.write(main_data)
        async with aiofiles.open(thumb_path, "wb") as f:
            await f.write(thumb_data)

        url = f"/media/photo_packs/{pack_id}/{filename}"
        thumb_url = f"/media/photo_packs/{pack_id}/{thumb_name}"

        img_record = PhotoPackImage(
            pack_id=pack_id,
            file_path=filepath,
            url=url,
            sort_order=order,
        )
        db.add(img_record)
        await db.flush()
        uploaded.append({"id": img_record.id, "url": url, "thumb_url": thumb_url, "filename": filename})

    await db.commit()
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
            }
            for img in images
        ],
    })
