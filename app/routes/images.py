import os
from typing import List

import aiofiles
from fastapi import APIRouter, Depends, Request, UploadFile, File
from fastapi.responses import JSONResponse, RedirectResponse
from PIL import UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.models.product import Product
from app.models.product_image import ProductImage
from app.services.image_processor import process_image

router = APIRouter(tags=["images"])


@router.post("/products/{product_id}/images")
async def upload_images(
    request: Request,
    product_id: int,
    files: List[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
):
    want_json = "application/json" in (request.headers.get("accept") or "")

    product = await db.get(Product, product_id)
    if not product:
        if want_json:
            return JSONResponse({"ok": False, "error": "Товар не найден"}, status_code=404)
        return RedirectResponse("/products", status_code=303)

    product_dir = os.path.join(settings.MEDIA_DIR, "products", str(product_id))
    os.makedirs(product_dir, exist_ok=True)

    result = await db.execute(
        select(ProductImage)
        .where(ProductImage.product_id == product_id)
        .order_by(ProductImage.sort_order.desc())
    )
    existing = result.scalars().all()
    max_order = existing[0].sort_order if existing else -1
    has_main = any(img.is_main for img in existing)

    uploaded = []
    for i, file in enumerate(files):
        if not file.filename:
            continue

        try:
            raw = await file.read()
            jpeg_bytes = process_image(raw, max_side=1600, quality=85)
        except (ValueError, OSError, UnidentifiedImageError) as exc:
            if want_json:
                uploaded.append({"filename": file.filename, "error": str(exc)})
            continue

        base = os.path.splitext(file.filename or "image")[0]
        clean_name = f"{base}.jpg"
        filename = f"{max_order + 1 + i}_{clean_name}"
        filepath = os.path.join(product_dir, filename)

        async with aiofiles.open(filepath, "wb") as f:
            await f.write(jpeg_bytes)

        url = f"/media/products/{product_id}/{filename}"
        is_main = not has_main and i == 0

        image = ProductImage(
            product_id=product_id,
            url=url,
            filename=filename,
            sort_order=max_order + 1 + i,
            is_main=is_main,
        )
        db.add(image)
        if is_main:
            has_main = True

        await db.flush()
        uploaded.append({"id": image.id, "url": url, "filename": filename, "is_main": is_main})

    await db.commit()

    if want_json:
        return JSONResponse({"ok": True, "images": uploaded})
    return RedirectResponse(f"/products/{product_id}", status_code=303)


@router.post("/products/{product_id}/images/{image_id}/main")
async def set_main_image(
    product_id: int, image_id: int, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(ProductImage).where(ProductImage.product_id == product_id)
    )
    images = result.scalars().all()
    for img in images:
        img.is_main = img.id == image_id
    await db.commit()
    return RedirectResponse(f"/products/{product_id}", status_code=303)


@router.post("/products/{product_id}/images/{image_id}/delete")
async def delete_image(
    request: Request,
    product_id: int, image_id: int, db: AsyncSession = Depends(get_db)
):
    want_json = "application/json" in (request.headers.get("accept") or "")
    image = await db.get(ProductImage, image_id)
    if image and image.product_id == product_id:
        filepath = os.path.normpath(os.path.join(settings.MEDIA_DIR, "products", str(product_id), image.filename))
        media_root = os.path.normpath(settings.MEDIA_DIR)
        if filepath.startswith(media_root) and os.path.exists(filepath):
            os.remove(filepath)
        await db.delete(image)
        await db.commit()
    if want_json:
        return JSONResponse({"ok": True})
    return RedirectResponse(f"/products/{product_id}", status_code=303)
