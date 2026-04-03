from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.models.item_stats import ItemStats
from app.models.product import Product
from app.services.image_sync import sync_images_from_crm
from app.services.stats_sync import sync_all_stats

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["analytics"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/analytics", response_class=HTMLResponse)
async def analytics_page(request: Request):
    return templates.TemplateResponse("analytics.html", {"request": request})


@router.get("/api/analytics")
async def analytics_data(db: AsyncSession = Depends(get_db)):
    """Return stats with trend and views_today for all products with avito_id."""
    all_stats_result = await db.execute(
        select(ItemStats).order_by(ItemStats.product_id, ItemStats.captured_at.desc())
    )
    all_stats = all_stats_result.scalars().all()

    # Group: latest and previous per product
    latest_by_product: dict[int, ItemStats] = {}
    prev_by_product: dict[int, ItemStats] = {}
    for s in all_stats:
        if s.product_id not in latest_by_product:
            latest_by_product[s.product_id] = s
        elif s.product_id not in prev_by_product:
            prev_by_product[s.product_id] = s

    from app.models.listing import Listing
    from app.models.listing_image import ListingImage

    products_result = await db.execute(
        select(Product)
        .options(
            selectinload(Product.account),
            selectinload(Product.images),
            selectinload(Product.listings).selectinload(Listing.images),
        )
        .where(Product.avito_id.isnot(None))
        .order_by(Product.id.desc())
    )
    products = products_result.scalars().all()

    today = datetime.now(timezone.utc).date()

    items = []
    for p in products:
        stat = latest_by_product.get(p.id)
        prev = prev_by_product.get(p.id)
        views = stat.views if stat else 0
        contacts = stat.contacts if stat else 0
        favorites = stat.favorites if stat else 0
        conversion = round(contacts / views * 100, 1) if views > 0 else 0

        # Trend: compare latest vs previous (only if 2+ snapshots)
        has_trend = stat is not None and prev is not None
        if has_trend:
            trend_delta = views - prev.views
            trend_dir = "up" if trend_delta > 0 else "down" if trend_delta < 0 else "flat"
        else:
            trend_delta = None
            trend_dir = None

        # Views today: latest(today) - previous(yesterday)
        views_today = None
        if stat and prev:
            latest_date = stat.captured_at.date() if stat.captured_at else None
            prev_date = prev.captured_at.date() if prev.captured_at else None
            if latest_date == today and prev_date and prev_date < today:
                views_today = views - prev.views

        # Image priority: 1) listing_images 2) product.image_url (CRM) 3) product_images
        resolved_image = None
        for ls in (p.listings or []):
            if ls.images:
                sorted_li = sorted(ls.images, key=lambda x: x.order)
                resolved_image = sorted_li[0].file_path
                break
        if not resolved_image and p.image_url:
            resolved_image = p.image_url
        if not resolved_image and p.images:
            sorted_imgs = sorted(p.images, key=lambda x: (not x.is_main, x.sort_order))
            resolved_image = sorted_imgs[0].url

        items.append({
            "id": p.id,
            "avito_id": p.avito_id,
            "title": p.title,
            "price": p.price,
            "status": p.status,
            "account": p.account.name if p.account else None,
            "image": resolved_image,
            "views": views,
            "contacts": contacts,
            "favorites": favorites,
            "conversion": conversion,
            "trend_dir": trend_dir,
            "trend_delta": trend_delta,
            "views_today": views_today,
        })

    last_sync_result = await db.execute(select(func.max(ItemStats.captured_at)))
    last_sync = last_sync_result.scalar()

    photos_synced = sum(1 for i in items if i["image"])
    photos_total = len(items)

    return JSONResponse({
        "items": items,
        "last_sync": last_sync.strftime("%d.%m.%Y %H:%M") if last_sync else None,
        "total": len(items),
        "photos_synced": photos_synced,
        "photos_total": photos_total,
    })


@router.get("/api/analytics/{product_id}/history")
async def product_history(product_id: int, db: AsyncSession = Depends(get_db)):
    """Return historical stats for a single product."""
    product = await db.get(Product, product_id)
    if not product:
        return JSONResponse({"ok": False, "error": "Товар не найден"}, status_code=404)

    result = await db.execute(
        select(ItemStats)
        .where(ItemStats.product_id == product_id)
        .order_by(ItemStats.captured_at.asc())
    )
    stats = result.scalars().all()

    history = [
        {
            "date": s.captured_at.strftime("%Y-%m-%d"),
            "views": s.views,
            "contacts": s.contacts,
            "favorites": s.favorites,
        }
        for s in stats
    ]

    return JSONResponse({
        "product_id": product_id,
        "avito_id": product.avito_id,
        "title": product.title,
        "history": history,
    })


@router.post("/api/stats/sync")
async def trigger_stats_sync(db: AsyncSession = Depends(get_db)):
    """Manual trigger for stats sync."""
    try:
        summaries = await sync_all_stats(db)
        return JSONResponse({"ok": True, "results": summaries})
    except Exception as e:
        logger.exception("Manual stats sync failed")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/api/images/sync-from-crm")
async def trigger_image_sync(db: AsyncSession = Depends(get_db)):
    """Sync image URLs from CRM chats to products."""
    try:
        result = await sync_images_from_crm(db)
        return JSONResponse({"ok": True, **result})
    except Exception as e:
        logger.exception("Image sync from CRM failed")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
