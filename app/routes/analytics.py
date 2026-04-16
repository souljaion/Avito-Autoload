from datetime import datetime, timedelta, timezone

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
from app.models.account import Account
from app.rate_limit import limiter
from app.services.avito_import import import_all_accounts
from app.services.image_sync import sync_images_from_crm
from app.services.stats_sync import sync_all_stats

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["analytics"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/analytics", response_class=HTMLResponse)
async def analytics_page(request: Request):
    return templates.TemplateResponse("analytics.html", {"request": request, "page_title": "Аналитика"})


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
    """Manual trigger for stats sync + import."""
    import time
    t0 = time.monotonic()
    try:
        # Import new items first
        import_results = await import_all_accounts(db)
        total_imported = sum(r.get("imported", 0) for r in import_results)
        total_marked_sold = sum(r.get("marked_sold", 0) for r in import_results)

        # Then sync stats
        summaries = await sync_all_stats(db)
        total_synced = sum(r.get("synced", 0) for r in summaries)

        duration = round(time.monotonic() - t0, 1)
        return JSONResponse({
            "ok": True,
            "results": summaries,
            "imported": total_imported,
            "marked_sold": total_marked_sold,
            "stats_updated": total_synced,
            "duration_seconds": duration,
        })
    except Exception as e:
        logger.exception("Manual stats sync failed")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.get("/api/analytics/efficiency")
async def analytics_efficiency(db: AsyncSession = Depends(get_db)):
    """Efficiency markers for active ads based on views delta in last 3 days."""
    from sqlalchemy import cast, Date
    cutoff = datetime.utcnow() - timedelta(days=3)
    today = datetime.utcnow().date()
    yesterday = today - timedelta(days=1)

    # Within the 3-day window: MAX, MIN views and count per product
    window_stmt = (
        select(
            ItemStats.product_id,
            func.max(ItemStats.views).label("max_views"),
            func.min(ItemStats.views).label("min_views"),
            func.count().label("cnt"),
        )
        .where(ItemStats.captured_at >= cutoff)
        .group_by(ItemStats.product_id)
    )
    window_result = await db.execute(window_stmt)
    window_map = {r.product_id: (r.max_views or 0, r.min_views or 0, r.cnt) for r in window_result.all()}

    # Baseline: latest snapshot before the 3-day window
    baseline_stmt = (
        select(
            ItemStats.product_id,
            func.max(ItemStats.views).label("baseline_views"),
        )
        .where(ItemStats.captured_at < cutoff)
        .group_by(ItemStats.product_id)
    )
    baseline_result = await db.execute(baseline_stmt)
    baseline_map = {r.product_id: r.baseline_views or 0 for r in baseline_result.all()}

    # views_3d = latest - baseline, or MAX - MIN within window if no baseline
    # single_snapshot tracks products with only 1 data point (no reliable delta)
    views_map = {}
    single_snapshot = set()
    for pid, (max_v, min_v, cnt) in window_map.items():
        baseline_v = baseline_map.get(pid)
        if baseline_v is not None:
            views_map[pid] = max(0, max_v - baseline_v)
        elif cnt >= 2:
            views_map[pid] = max(0, max_v - min_v)
        else:
            views_map[pid] = None
            single_snapshot.add(pid)

    # --- Totals: MAX(views), MAX(contacts) per product (all time) ---
    totals_stmt = (
        select(
            ItemStats.product_id,
            func.max(ItemStats.views).label("views_total"),
            func.max(ItemStats.contacts).label("contacts_total"),
        )
        .group_by(ItemStats.product_id)
    )
    totals_result = await db.execute(totals_stmt)
    totals_map = {r.product_id: (r.views_total or 0, r.contacts_total or 0) for r in totals_result.all()}

    # --- Today deltas: MAX for today minus MAX for yesterday ---
    today_stmt = (
        select(
            ItemStats.product_id,
            func.max(ItemStats.views).label("v"),
            func.max(ItemStats.contacts).label("c"),
        )
        .where(cast(ItemStats.captured_at, Date) == today)
        .group_by(ItemStats.product_id)
    )
    today_result = await db.execute(today_stmt)
    today_map = {r.product_id: (r.v or 0, r.c or 0) for r in today_result.all()}

    yesterday_stmt = (
        select(
            ItemStats.product_id,
            func.max(ItemStats.views).label("v"),
            func.max(ItemStats.contacts).label("c"),
        )
        .where(cast(ItemStats.captured_at, Date) == yesterday)
        .group_by(ItemStats.product_id)
    )
    yesterday_result = await db.execute(yesterday_stmt)
    yesterday_map = {r.product_id: (r.v or 0, r.c or 0) for r in yesterday_result.all()}

    # Active products with avito_id
    products_result = await db.execute(
        select(Product)
        .options(selectinload(Product.account), selectinload(Product.images))
        .where(
            Product.avito_id.isnot(None),
            Product.status.in_(["active", "published", "imported"]),
        )
        .order_by(Product.id.desc())
    )
    products = products_result.scalars().all()

    now = datetime.utcnow()
    items = []
    summary = {"dead": 0, "weak": 0, "alive": 0, "unknown": 0}
    for p in products:
        if p.id in single_snapshot:
            v = None
            marker = "unknown"
        elif p.id in views_map:
            v = views_map[p.id]
            if v == 0:
                marker = "dead"
            elif v < 10:
                marker = "weak"
            else:
                marker = "alive"
        else:
            v = None
            marker = "unknown"
        summary[marker] += 1

        # Resolve image
        image = None
        if p.images:
            sorted_imgs = sorted(p.images, key=lambda x: (not x.is_main, x.sort_order))
            image = sorted_imgs[0].url
        elif p.image_url:
            image = p.image_url

        # Totals
        vt, ct = totals_map.get(p.id, (None, None))

        # Today deltas
        views_today = None
        contacts_today = None
        if p.id in today_map and p.id in yesterday_map:
            tv, tc = today_map[p.id]
            yv, yc = yesterday_map[p.id]
            views_today = max(0, tv - yv)
            contacts_today = max(0, tc - yc)
        elif p.id in today_map:
            # No yesterday data — can't compute delta
            views_today = None
            contacts_today = None

        # Published date: only for products published through the platform
        pub_dt = p.published_at if p.published_at and p.status in ("active", "published") else None
        if pub_dt:
            pub_naive = pub_dt.replace(tzinfo=None) if pub_dt.tzinfo else pub_dt
            published_at_str = pub_naive.strftime("%d.%m.%Y")
            days_ago = (now - pub_naive).days
        else:
            published_at_str = None
            days_ago = None

        items.append({
            "product_id": p.id,
            "title": p.title,
            "account_name": p.account.name if p.account else None,
            "account_id": p.account_id,
            "avito_id": p.avito_id,
            "views_3d": v,
            "marker": marker,
            "price": p.price,
            "image": image,
            "views_total": vt,
            "views_today": views_today,
            "contacts_total": ct,
            "contacts_today": contacts_today,
            "published_at": published_at_str,
            "days_ago": days_ago,
            "avito_messages": (p.extra or {}).get("avito_messages") or None,
        })

    last_sync_result = await db.execute(select(func.max(ItemStats.captured_at)))
    last_sync = last_sync_result.scalar()
    last_sync_str = last_sync.strftime("%d.%m.%Y %H:%M") if last_sync else None

    # Per-account breakdown + top3
    acc_data: dict[int, dict] = {}
    for item in items:
        aid = item["account_id"]
        if aid is None:
            continue
        if aid not in acc_data:
            acc_data[aid] = {
                "account_id": aid,
                "account_name": item["account_name"],
                "counts": {"dead": 0, "weak": 0, "alive": 0, "unknown": 0},
                "top3": [],
                "last_sync": last_sync_str,
            }
        acc_data[aid]["counts"][item["marker"]] += 1
        if item["views_3d"] is not None:
            acc_data[aid]["top3"].append(item)

    # Sort top3 per account and global
    for ad in acc_data.values():
        ad["top3"] = sorted(ad["top3"], key=lambda x: x["views_3d"] or 0, reverse=True)[:3]
        ad["top3"] = [{"title": t["title"], "views": t["views_3d"], "marker": t["marker"]} for t in ad["top3"]]

    global_top3 = sorted(
        [i for i in items if i["views_3d"] is not None],
        key=lambda x: x["views_3d"] or 0, reverse=True,
    )[:3]
    global_top3 = [{"title": t["title"], "views": t["views_3d"], "marker": t["marker"]} for t in global_top3]

    total_accounts = len(acc_data)

    return JSONResponse({
        "products": items,
        "summary": summary,
        "last_sync": last_sync_str,
        "accounts": list(acc_data.values()),
        "global_top3": global_top3,
        "total_accounts": total_accounts,
        "total_products": len(items),
    })


@router.get("/api/analytics/fees")
@limiter.limit("10/minute")
async def analytics_fees(
    request: Request,
    account_id: int,
    report_id: int | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Fetch fee data for a report. If report_id is omitted, use last completed report."""
    from app.models.autoload_report import AutoloadReport
    from app.services.avito_client import AvitoClient

    account = await db.get(Account, account_id)
    if not account:
        return JSONResponse({"ok": False, "error": "Аккаунт не найден"}, status_code=404)

    report_status: str | None = None
    if report_id is None:
        result = await db.execute(
            select(AutoloadReport)
            .where(AutoloadReport.account_id == account_id)
            .order_by(AutoloadReport.created_at.desc())
            .limit(1)
        )
        report = result.scalars().first()
        if not report or not report.avito_report_id:
            return JSONResponse({"ok": False, "error": "Нет отчётов для этого аккаунта"}, status_code=404)
        report_id = int(report.avito_report_id)
        report_status = report.status
    else:
        # User-supplied report_id — try to find status in DB for cache TTL hint
        result = await db.execute(
            select(AutoloadReport).where(
                AutoloadReport.account_id == account_id,
                AutoloadReport.avito_report_id == str(report_id),
            )
        )
        report = result.scalars().first()
        if report:
            report_status = report.status

    client = AvitoClient(account, db)
    try:
        fees_data = await client.get_report_fees(report_id, report_status=report_status)
    except Exception as e:
        logger.exception("Fees fetch failed", account_id=account_id, report_id=report_id)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
    finally:
        await client.close()

    total_fees_rub = sum(
        f.get("amount_total", 0) for f in fees_data.get("fees", [])
    )

    return JSONResponse({
        "ok": True,
        "report_id": report_id,
        "account_name": account.name,
        "fees": fees_data.get("fees", []),
        "total_fees_rub": total_fees_rub,
    })


@router.post("/api/images/sync-from-crm")
async def trigger_image_sync(db: AsyncSession = Depends(get_db)):
    """Sync image URLs from CRM chats to products."""
    try:
        result = await sync_images_from_crm(db)
        return JSONResponse({"ok": True, **result})
    except Exception as e:
        logger.exception("Image sync from CRM failed")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
