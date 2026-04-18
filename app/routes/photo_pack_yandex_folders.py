"""Routes for Yandex.Disk folder management on photo packs."""

import os

import httpx
import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db, utc_now
from app.models.photo_pack import PhotoPack
from app.models.photo_pack_image import PhotoPackImage
from app.models.photo_pack_yandex_folder import PhotoPackYandexFolder
from app.services.yandex_disk import extract_public_key, list_folder, RateLimitError

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["photo-pack-yandex-folders"])


@router.get("/api/photo-packs/{pack_id}/yandex-folders")
async def get_pack_yandex_folders(pack_id: int, db: AsyncSession = Depends(get_db)):
    """List Yandex.Disk folders with file listings for a photo pack."""
    pack = await db.get(PhotoPack, pack_id)
    if not pack:
        return JSONResponse({"ok": False, "error": "Пак не найден"}, status_code=404)

    result = await db.execute(
        select(PhotoPackYandexFolder)
        .where(PhotoPackYandexFolder.photo_pack_id == pack_id)
        .order_by(PhotoPackYandexFolder.id)
    )
    folders = result.scalars().all()

    # Get existing images from Yandex for this pack
    imgs_result = await db.execute(
        select(PhotoPackImage)
        .where(
            PhotoPackImage.pack_id == pack_id,
            PhotoPackImage.source_type == "yandex_disk",
        )
    )
    existing_images = imgs_result.scalars().all()
    selected_paths = {img.yandex_file_path for img in existing_images if img.yandex_file_path}

    items = []
    for folder in folders:
        files = []
        folder_error = folder.error
        try:
            raw_files = await list_folder(folder.public_url)
            folder.last_synced_at = utc_now()
            folder.error = None
            folder_error = None
            for f in raw_files:
                files.append({
                    "path": f["path"],
                    "name": f["name"],
                    "preview_url": f["preview_url"],
                    "size": f["size"],
                    "md5": f["md5"],
                    "selected": f["path"] in selected_paths,
                })
        except Exception as e:
            folder_error = str(e)[:500]
            folder.error = folder_error
            logger.warning("pack_yandex_folders.list_error", folder_id=folder.id, error=str(e))

        await db.commit()

        items.append({
            "folder_id": folder.id,
            "folder_name": folder.folder_name,
            "public_url": folder.public_url,
            "last_synced_at": folder.last_synced_at.isoformat() if folder.last_synced_at else None,
            "error": folder_error,
            "files": files,
        })

    return JSONResponse({"ok": True, "folders": items})


@router.post("/api/photo-packs/{pack_id}/yandex-folders")
async def add_pack_yandex_folder(pack_id: int, request_data: dict, db: AsyncSession = Depends(get_db)):
    """Add a Yandex.Disk folder to a photo pack."""
    pack = await db.get(PhotoPack, pack_id)
    if not pack:
        return JSONResponse({"ok": False, "error": "Пак не найден"}, status_code=404)

    public_url = (request_data.get("public_url") or "").strip()
    folder_name = (request_data.get("folder_name") or "").strip() or None

    try:
        public_key = extract_public_key(public_url)
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    try:
        files = await list_folder(public_url)
    except ValueError as e:
        return JSONResponse({"ok": False, "error": f"Папка недоступна: {e}"}, status_code=400)
    except RateLimitError:
        return JSONResponse({"ok": False, "error": "Яндекс.Диск: лимит запросов"}, status_code=429)
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (400, 404):
            return JSONResponse(
                {"ok": False, "error": "Папка не найдена или недоступна. Проверьте, что ссылка публичная и папка не удалена."},
                status_code=400,
            )
        raise

    folder = PhotoPackYandexFolder(
        photo_pack_id=pack_id,
        public_url=public_url,
        public_key=public_key,
        folder_name=folder_name,
        last_synced_at=utc_now(),
    )
    db.add(folder)
    await db.commit()

    file_items = [{
        "path": f["path"],
        "name": f["name"],
        "preview_url": f["preview_url"],
        "size": f["size"],
        "md5": f["md5"],
        "selected": False,
    } for f in files]

    return JSONResponse({
        "ok": True,
        "folder_id": folder.id,
        "folder_name": folder.folder_name,
        "public_url": folder.public_url,
        "last_synced_at": folder.last_synced_at.isoformat() if folder.last_synced_at else None,
        "error": None,
        "files": file_items,
    }, status_code=201)


@router.delete("/api/photo-packs/{pack_id}/yandex-folders/{folder_id}")
async def delete_pack_yandex_folder(
    pack_id: int,
    folder_id: int,
    delete_images: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """Delete a Yandex.Disk folder binding from a photo pack."""
    folder = await db.get(PhotoPackYandexFolder, folder_id)
    if not folder or folder.photo_pack_id != pack_id:
        return JSONResponse({"ok": False, "error": "Папка не найдена"}, status_code=404)

    if delete_images:
        imgs_result = await db.execute(
            select(PhotoPackImage).where(
                PhotoPackImage.yandex_folder_id == folder_id,
                PhotoPackImage.pack_id == pack_id,
            )
        )
        for img in imgs_result.scalars().all():
            _delete_local_file(img.url)
            await db.delete(img)

    await db.delete(folder)
    await db.commit()
    return JSONResponse({"ok": True}, status_code=200)


@router.put("/api/photo-packs/{pack_id}/yandex-folders/{folder_id}/selection")
async def update_pack_selection(
    pack_id: int,
    folder_id: int,
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    """Sync photo_pack_images with the selected Yandex.Disk files."""
    folder = await db.get(PhotoPackYandexFolder, folder_id)
    if not folder or folder.photo_pack_id != pack_id:
        return JSONResponse({"ok": False, "error": "Папка не найдена"}, status_code=404)

    selected_paths = set(body.get("selected_paths", []))

    # Get existing images from this folder
    imgs_result = await db.execute(
        select(PhotoPackImage).where(
            PhotoPackImage.yandex_folder_id == folder_id,
            PhotoPackImage.pack_id == pack_id,
        )
    )
    existing = imgs_result.scalars().all()
    existing_by_path = {img.yandex_file_path: img for img in existing if img.yandex_file_path}

    # Get max sort_order for this pack
    max_order_result = await db.execute(
        select(PhotoPackImage.sort_order)
        .where(PhotoPackImage.pack_id == pack_id)
        .order_by(PhotoPackImage.sort_order.desc())
        .limit(1)
    )
    max_order_row = max_order_result.scalar_one_or_none()
    next_order = (max_order_row or -1) + 1

    # Remove deselected
    for path, img in existing_by_path.items():
        if path not in selected_paths:
            _delete_local_file(img.url)
            await db.delete(img)

    # Add newly selected
    added = 0
    for path in sorted(selected_paths):
        if path in existing_by_path:
            continue
        name = path.rsplit("/", 1)[-1] if "/" in path else path
        safe_name = name.replace(" ", "_")[:200]
        img = PhotoPackImage(
            pack_id=pack_id,
            file_path="",   # placeholder — set by download job
            url="",         # placeholder — set by download job
            sort_order=next_order + added,
            source_type="yandex_disk",
            yandex_folder_id=folder_id,
            yandex_file_path=path,
            download_status="pending",
        )
        db.add(img)
        added += 1

    await db.commit()

    # Return updated state
    imgs_result2 = await db.execute(
        select(PhotoPackImage).where(
            PhotoPackImage.yandex_folder_id == folder_id,
            PhotoPackImage.pack_id == pack_id,
        ).order_by(PhotoPackImage.sort_order)
    )
    result_images = [{
        "id": img.id,
        "yandex_file_path": img.yandex_file_path,
        "download_status": img.download_status,
        "sort_order": img.sort_order,
    } for img in imgs_result2.scalars().all()]

    return JSONResponse({"ok": True, "added": added, "images": result_images})


@router.put("/api/photo-packs/{pack_id}/images/order")
async def update_pack_image_order(pack_id: int, body: dict, db: AsyncSession = Depends(get_db)):
    """Reorder photo pack images."""
    ordered_ids = body.get("ordered_image_ids", [])
    if not ordered_ids:
        return JSONResponse({"ok": False, "error": "No image IDs provided"}, status_code=400)

    result = await db.execute(
        select(PhotoPackImage).where(
            PhotoPackImage.pack_id == pack_id,
            PhotoPackImage.id.in_(ordered_ids),
        )
    )
    images = {img.id: img for img in result.scalars().all()}

    if len(images) != len(ordered_ids):
        return JSONResponse({"ok": False, "error": "Some image IDs not found"}, status_code=400)

    for order, img_id in enumerate(ordered_ids):
        images[img_id].sort_order = order

    await db.commit()
    return JSONResponse({"ok": True})


@router.patch("/api/photo-packs/{pack_id}/images/{image_id}/retry-download")
async def retry_pack_download(pack_id: int, image_id: int, db: AsyncSession = Depends(get_db)):
    """Reset a failed download to pending so the background job retries it."""
    img = await db.get(PhotoPackImage, image_id)
    if not img or img.pack_id != pack_id:
        return JSONResponse({"ok": False, "error": "Image not found"}, status_code=404)
    if img.download_status != "failed":
        return JSONResponse({"ok": False, "error": "Not in failed state"}, status_code=409)

    img.download_status = "pending"
    img.download_error = None
    img.download_attempts = 0
    await db.commit()
    return JSONResponse({"ok": True})


def _delete_local_file(url: str):
    """Delete a local file by its /media/... URL. Silently ignores errors."""
    if not url or not url.startswith("/media/"):
        return
    rel = url[len("/media/"):]
    filepath = os.path.normpath(os.path.join(settings.MEDIA_DIR, rel))
    media_root = os.path.normpath(settings.MEDIA_DIR)
    if not filepath.startswith(media_root):
        return
    try:
        os.remove(filepath)
    except OSError:
        pass
