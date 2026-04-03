import os
import shutil

import aiofiles
import structlog
from fastapi import APIRouter, Depends, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from PIL import UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db import get_db
from app.models.account import Account
from app.models.listing import Listing
from app.models.listing_image import ListingImage
from app.models.product import Product
from app.services.image_processor import process_image

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["listings"])
templates = Jinja2Templates(directory="app/templates")


# ── API: List listings for products page ──

@router.get("/api/listings")
async def list_listings(
    status: str | None = None,
    account_id: int | None = None,
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Listing)
        .options(
            selectinload(Listing.product).selectinload(Product.images),
            selectinload(Listing.account),
            selectinload(Listing.images),
        )
        .order_by(Listing.updated_at.desc())
    )
    if status and status != "all":
        stmt = stmt.where(Listing.status == status)
    if account_id:
        stmt = stmt.where(Listing.account_id == account_id)

    result = await db.execute(stmt)
    listings = result.scalars().all()

    items = []
    for ls in listings:
        first_img = None
        if ls.images:
            sorted_imgs = sorted(ls.images, key=lambda x: x.order)
            first_img = sorted_imgs[0].file_path
        elif ls.product and ls.product.images:
            sorted_imgs = sorted(ls.product.images, key=lambda x: (not x.is_main, x.sort_order))
            first_img = sorted_imgs[0].url

        items.append({
            "id": ls.id,
            "product_id": ls.product_id,
            "title": ls.product.title if ls.product else "—",
            "price": ls.product.price if ls.product else None,
            "brand": ls.product.brand if ls.product else None,
            "account_id": ls.account_id,
            "account": ls.account.name if ls.account else "—",
            "status": ls.status,
            "avito_id": ls.avito_id,
            "scheduled_at": ls.scheduled_at.strftime("%d.%m.%Y %H:%M") if ls.scheduled_at else None,
            "published_at": ls.published_at.strftime("%d.%m.%Y %H:%M") if ls.published_at else None,
            "image": first_img,
            "image_count": len(ls.images),
        })

    return JSONResponse({"items": items})


# ── Create listing for product ──

@router.post("/products/{product_id}/listings")
async def create_listing(product_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    body = await request.json()
    account_id = body.get("account_id")
    scheduled_at_str = body.get("scheduled_at")

    if not account_id:
        return JSONResponse({"ok": False, "error": "Не указан account_id"}, status_code=400)

    product = await db.get(Product, product_id)
    if not product:
        return JSONResponse({"ok": False, "error": "Товар не найден"}, status_code=404)

    status = "draft"
    scheduled_at = None
    if scheduled_at_str:
        from datetime import datetime as dt
        try:
            scheduled_at = dt.fromisoformat(scheduled_at_str)
            status = "scheduled"
        except ValueError:
            pass

    listing = Listing(
        product_id=product_id,
        account_id=int(account_id),
        status=status,
        scheduled_at=scheduled_at,
    )
    db.add(listing)
    await db.commit()
    return JSONResponse({"ok": True, "id": listing.id})


# ── Edit listing page ──

@router.get("/listings/{listing_id}/edit", response_class=HTMLResponse)
async def edit_listing_page(request: Request, listing_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Listing)
        .options(
            selectinload(Listing.product).selectinload(Product.images),
            selectinload(Listing.account),
            selectinload(Listing.images),
        )
        .where(Listing.id == listing_id)
    )
    listing = result.scalar_one_or_none()
    if not listing:
        return HTMLResponse("Listing не найден", status_code=404)

    accs = await db.execute(select(Account).order_by(Account.name))

    return templates.TemplateResponse("listings/edit.html", {
        "request": request,
        "listing": listing,
        "product": listing.product,
        "accounts": accs.scalars().all(),
    })


# ── PATCH listing ──

@router.patch("/listings/{listing_id}")
async def patch_listing(listing_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    listing = await db.get(Listing, listing_id)
    if not listing:
        return JSONResponse({"ok": False, "error": "Listing не найден"}, status_code=404)

    body = await request.json()

    if "status" in body:
        listing.status = body["status"]
    if "account_id" in body:
        listing.account_id = int(body["account_id"])
    if "scheduled_at" in body:
        val = body["scheduled_at"]
        if val:
            from datetime import datetime as dt
            try:
                listing.scheduled_at = dt.fromisoformat(val)
            except ValueError:
                pass
        else:
            listing.scheduled_at = None

    await db.commit()
    return JSONResponse({"ok": True, "id": listing.id, "status": listing.status})


# ── Update product fields from listing edit ──

@router.post("/listings/{listing_id}/edit")
async def update_listing_form(
    request: Request,
    listing_id: int,
    title: str = Form(...),
    description: str = Form(""),
    price: str = Form(""),
    brand: str = Form(""),
    color: str = Form(""),
    status: str = Form("draft"),
    account_id: str = Form(""),
    scheduled_at: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Listing).options(selectinload(Listing.product)).where(Listing.id == listing_id)
    )
    listing = result.scalar_one_or_none()
    if not listing:
        return HTMLResponse("Listing не найден", status_code=404)

    # Update product fields (affects all listings of this product)
    p = listing.product
    if p:
        p.title = title
        p.description = description or None
        try:
            p.price = int(price) if price and price.strip() else None
        except (ValueError, TypeError):
            pass
        p.brand = brand or None
        p.color = color or None

    # Update listing fields
    if account_id:
        listing.account_id = int(account_id)
    listing.status = status
    if scheduled_at:
        from datetime import datetime as dt
        try:
            listing.scheduled_at = dt.fromisoformat(scheduled_at)
            if status != "published":
                listing.status = "scheduled"
        except ValueError:
            pass
    elif listing.status == "scheduled":
        listing.scheduled_at = None
        listing.status = "draft"

    await db.commit()
    return RedirectResponse(f"/listings/{listing_id}/edit", status_code=303)


# ── Upload images for listing ──

@router.post("/listings/{listing_id}/images")
async def upload_listing_images(
    request: Request,
    listing_id: int,
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
):
    want_json = "application/json" in (request.headers.get("accept") or "")

    listing = await db.get(Listing, listing_id)
    if not listing:
        if want_json:
            return JSONResponse({"ok": False, "error": "Listing не найден"}, status_code=404)
        return RedirectResponse(f"/listings/{listing_id}/edit", status_code=303)

    listing_dir = os.path.join(settings.MEDIA_DIR, "listings", str(listing_id))
    os.makedirs(listing_dir, exist_ok=True)

    # Get max order
    result = await db.execute(
        select(ListingImage)
        .where(ListingImage.listing_id == listing_id)
        .order_by(ListingImage.order.desc())
    )
    existing = result.scalars().all()
    max_order = existing[0].order if existing else -1

    uploaded = []
    for i, file in enumerate(files):
        if not file.filename:
            continue
        try:
            raw = await file.read()
            jpeg_bytes = process_image(raw, max_side=1600, quality=85)
        except (ValueError, OSError, UnidentifiedImageError):
            continue

        base = os.path.splitext(file.filename or "image")[0]
        clean_name = f"{base}.jpg"
        filename = f"{max_order + 1 + i}_{clean_name}"
        filepath = os.path.join(listing_dir, filename)
        async with aiofiles.open(filepath, "wb") as f:
            await f.write(jpeg_bytes)

        url = f"/media/listings/{listing_id}/{filename}"
        img = ListingImage(
            listing_id=listing_id,
            file_path=url,
            order=max_order + 1 + i,
        )
        db.add(img)
        await db.flush()
        uploaded.append({"id": img.id, "url": url, "order": img.order})

    await db.commit()

    if want_json:
        return JSONResponse({"ok": True, "images": uploaded})
    return RedirectResponse(f"/listings/{listing_id}/edit", status_code=303)


# ── Delete listing image ──

@router.post("/listings/{listing_id}/images/{image_id}/delete")
async def delete_listing_image(
    request: Request, listing_id: int, image_id: int, db: AsyncSession = Depends(get_db)
):
    want_json = "application/json" in (request.headers.get("accept") or "")
    image = await db.get(ListingImage, image_id)
    if image and image.listing_id == listing_id:
        safe_name = image.file_path.replace("/media/", "", 1) if image.file_path.startswith("/media/") else image.file_path
        full_path = os.path.normpath(os.path.join(settings.MEDIA_DIR, safe_name))
        media_root = os.path.normpath(settings.MEDIA_DIR)
        if full_path.startswith(media_root) and os.path.exists(full_path):
            os.remove(full_path)
        await db.delete(image)
        await db.commit()
    if want_json:
        return JSONResponse({"ok": True})
    return RedirectResponse(f"/listings/{listing_id}/edit", status_code=303)


# ── Delete listing ──

@router.delete("/listings/{listing_id}")
async def delete_listing(listing_id: int, db: AsyncSession = Depends(get_db)):
    listing = await db.get(Listing, listing_id)
    if not listing:
        return JSONResponse({"ok": False, "error": "Listing не найден"}, status_code=404)

    # Delete media folder
    listing_dir = os.path.join(settings.MEDIA_DIR, "listings", str(listing_id))
    if os.path.isdir(listing_dir):
        shutil.rmtree(listing_dir, ignore_errors=True)

    await db.delete(listing)
    await db.commit()
    return JSONResponse({"ok": True})
