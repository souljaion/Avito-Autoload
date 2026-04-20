from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func, cast, Date, extract
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.models.account import Account
from app.models.item_stats import ItemStats
from app.models.model import Model
from app.models.photo_pack import PhotoPack
from app.models.product import Product
from app.services.feed_generator import get_missing_fields

MSK = ZoneInfo("Europe/Moscow")

router = APIRouter(tags=["schedule"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/schedule", response_class=HTMLResponse)
async def schedule_page(
    request: Request,
    product_id: int | None = None,
    db: AsyncSession = Depends(get_db),
):
    if product_id:
        product = await db.get(Product, product_id)
        if product and product.account_id:
            return RedirectResponse(
                f"/schedule/{product.account_id}?highlight={product_id}",
                status_code=302,
            )

    accs = await db.execute(select(Account).order_by(Account.name))
    accounts = accs.scalars().all()
    return templates.TemplateResponse("schedule.html", {"request": request, "accounts": accounts, "page_title": "Расписание"})


@router.get("/api/schedule/overview")
async def schedule_overview(db: AsyncSession = Depends(get_db)):
    """Dashboard data: global metrics, hourly load, per-account cards."""
    accs = await db.execute(select(Account).order_by(Account.name))
    accounts = accs.scalars().all()

    today = datetime.now(timezone.utc).replace(tzinfo=None).date()

    # Per-account counts
    counts_result = await db.execute(
        select(
            Product.account_id,
            func.count().filter(Product.status.in_(["active", "published", "imported"])).label("active"),
            func.count().filter(Product.status == "scheduled").label("scheduled"),
            func.count().filter(Product.status == "draft").label("draft"),
            func.count().filter(
                Product.status == "scheduled",
                cast(Product.scheduled_at, Date) == today,
            ).label("scheduled_today"),
            func.count().filter(
                cast(Product.published_at, Date) == today,
            ).label("published_today"),
        )
        .where(Product.account_id.isnot(None))
        .group_by(Product.account_id)
    )
    counts = {}
    for r in counts_result.all():
        counts[r.account_id] = {
            "active": r.active, "scheduled": r.scheduled, "draft": r.draft,
            "scheduled_today": r.scheduled_today, "published_today": r.published_today,
        }

    # Global totals
    global_scheduled_today = sum(c["scheduled_today"] for c in counts.values())
    global_published_today = sum(c["published_today"] for c in counts.values())
    global_drafts = sum(c["draft"] for c in counts.values())

    # Nearest feed time
    next_feed = None
    for acc in accounts:
        if acc.avito_sync_minute is not None:
            now_msk = datetime.now(MSK)
            # Next occurrence of XX:sync_minute
            candidate = now_msk.replace(minute=acc.avito_sync_minute, second=0, microsecond=0)
            if candidate <= now_msk:
                candidate += timedelta(hours=1)
            feed_str = candidate.strftime("%H:%M")
            if next_feed is None or candidate < next_feed[1]:
                next_feed = (f"{feed_str} \u00b7 {acc.name}", candidate)

    # Hourly load for today (in MSK)
    msk_offset = func.make_interval(0, 0, 0, 0, 3, 0, 0)
    today_msk = datetime.now(MSK).date()
    hourly_result = await db.execute(
        select(
            extract("hour", Product.scheduled_at + msk_offset).label("h"),
            func.count().label("cnt"),
        )
        .where(
            Product.status == "scheduled",
            cast(Product.scheduled_at + msk_offset, Date) == today_msk,
        )
        .group_by("h")
    )
    hourly_map = {int(r.h): r.cnt for r in hourly_result.all()}
    hourly_load = [hourly_map.get(h, 0) for h in range(24)]

    # Upcoming scheduled per account (top 3 today)
    upcoming_result = await db.execute(
        select(Product)
        .where(
            Product.status == "scheduled",
            Product.account_id.isnot(None),
        )
        .order_by(Product.scheduled_at.asc())
    )
    upcoming_by_acc: dict[int, list] = {}
    for p in upcoming_result.scalars().all():
        if p.account_id not in upcoming_by_acc:
            upcoming_by_acc[p.account_id] = []
        if len(upcoming_by_acc[p.account_id]) < 3:
            sched_str = None
            if p.scheduled_at:
                msk = p.scheduled_at.replace(tzinfo=timezone.utc).astimezone(MSK)
                sched_str = msk.strftime("%H:%M")
            upcoming_by_acc[p.account_id].append({
                "product_id": p.id,
                "title": p.title[:35] + ("..." if len(p.title) > 35 else ""),
                "price": p.price,
                "status": p.status,
                "scheduled_at": sched_str,
            })

    items = []
    for acc in accounts:
        c = counts.get(acc.id, {"active": 0, "scheduled": 0, "draft": 0, "scheduled_today": 0, "published_today": 0})
        feed_time = None
        if acc.avito_sync_minute is not None:
            feed_time = f"XX:{acc.avito_sync_minute:02d}"
        items.append({
            "id": acc.id,
            "name": acc.name,
            "active": c["active"],
            "scheduled": c["scheduled"],
            "draft": c["draft"],
            "scheduled_today": c["scheduled_today"],
            "published_today": c["published_today"],
            "upcoming": upcoming_by_acc.get(acc.id, []),
            "sync_minute": acc.avito_sync_minute,
            "feed_time": feed_time,
        })

    return JSONResponse({
        "accounts": items,
        "totals": {
            "scheduled_today": global_scheduled_today,
            "published_today": global_published_today,
            "drafts": global_drafts,
            "next_feed": next_feed[0] if next_feed else None,
        },
        "hourly_load": hourly_load,
    })


@router.get("/schedule/{account_id}", response_class=HTMLResponse)
async def schedule_account_page(request: Request, account_id: int, db: AsyncSession = Depends(get_db)):
    account = await db.get(Account, account_id)
    if not account:
        return HTMLResponse("Аккаунт не найден", status_code=404)
    return templates.TemplateResponse("schedule_account.html", {"request": request, "account": account, "page_title": "Расписание"})


@router.get("/api/schedule/{account_id}")
async def schedule_account_data(account_id: int, db: AsyncSession = Depends(get_db)):
    """Full data for per-account schedule page: metrics, hourly, queue, drafts, active."""
    today = datetime.now(timezone.utc).replace(tzinfo=None).date()
    yesterday = today - timedelta(days=1)

    # ── Metrics ──
    metrics_result = await db.execute(
        select(
            func.count().filter(Product.status.in_(["active", "published", "imported"])).label("active_count"),
            func.count().filter(
                Product.status == "scheduled",
                cast(Product.scheduled_at, Date) == today,
            ).label("scheduled_today"),
            func.count().filter(
                cast(Product.published_at, Date) == today,
            ).label("published_today"),
            func.count().filter(Product.status == "draft").label("draft_count"),
        )
        .where(Product.account_id == account_id)
    )
    m = metrics_result.one()

    # ── Dead count (marker logic) ──
    cutoff_5d = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=5)
    active_pids_result = await db.execute(
        select(Product.id).where(
            Product.account_id == account_id,
            Product.avito_id.isnot(None),
            Product.status.in_(["active", "published", "imported"]),
        )
    )
    active_pids = [r[0] for r in active_pids_result.all()]

    dead_count = 0
    views_5d_map: dict[int, int | None] = {}
    single_snapshot: set[int] = set()

    if active_pids:
        window_result = await db.execute(
            select(
                ItemStats.product_id,
                func.max(ItemStats.views).label("max_views"),
                func.min(ItemStats.views).label("min_views"),
                func.count().label("cnt"),
            )
            .where(ItemStats.captured_at >= cutoff_5d, ItemStats.product_id.in_(active_pids))
            .group_by(ItemStats.product_id)
        )
        window_map = {r.product_id: (r.max_views or 0, r.min_views or 0, r.cnt) for r in window_result.all()}

        baseline_result = await db.execute(
            select(
                ItemStats.product_id,
                func.max(ItemStats.views).label("baseline_views"),
            )
            .where(ItemStats.captured_at < cutoff_5d, ItemStats.product_id.in_(active_pids))
            .group_by(ItemStats.product_id)
        )
        baseline_map = {r.product_id: r.baseline_views or 0 for r in baseline_result.all()}

        for pid, (max_v, min_v, cnt) in window_map.items():
            baseline_v = baseline_map.get(pid)
            if baseline_v is not None:
                views_5d_map[pid] = max(0, max_v - baseline_v)
            elif cnt >= 2:
                views_5d_map[pid] = max(0, max_v - min_v)
            else:
                views_5d_map[pid] = None
                single_snapshot.add(pid)

        for pid in active_pids:
            if pid in single_snapshot:
                continue
            v = views_5d_map.get(pid)
            if v is not None and v < 20:
                dead_count += 1

    # ── Hourly load ──
    msk_offset = func.make_interval(0, 0, 0, 0, 3, 0, 0)
    today_msk = datetime.now(MSK).date()
    hourly_result = await db.execute(
        select(
            extract("hour", Product.scheduled_at + msk_offset).label("h"),
            func.count().label("cnt"),
        )
        .where(
            Product.account_id == account_id,
            Product.status == "scheduled",
            cast(Product.scheduled_at + msk_offset, Date) == today_msk,
        )
        .group_by("h")
    )
    hourly_map = {int(r.h): r.cnt for r in hourly_result.all()}
    hourly_load = [hourly_map.get(h, 0) for h in range(24)]

    # ── Queue (scheduled products) ──
    sched_result = await db.execute(
        select(Product)
        .options(selectinload(Product.images))
        .where(Product.account_id == account_id, Product.status == "scheduled")
        .order_by(Product.scheduled_at.asc(), Product.id.asc())
    )
    scheduled = []
    for p in sched_result.scalars().all():
        img = _resolve_image(p)
        sched_at = None
        sched_iso = None
        date_group = None
        if p.scheduled_at:
            msk = p.scheduled_at.replace(tzinfo=timezone.utc).astimezone(MSK)
            sched_at = msk.strftime("%d.%m.%Y %H:%M")
            sched_iso = p.scheduled_at.isoformat()
            d = msk.date()
            today_msk = datetime.now(MSK).date()
            if d == today_msk:
                date_group = "Сегодня"
            elif d == today_msk + timedelta(days=1):
                date_group = "Завтра"
            else:
                date_group = d.strftime("%d.%m.%Y")
        scheduled.append({
            "product_id": p.id,
            "title": p.title,
            "price": p.price,
            "size": p.size,
            "image": img,
            "status": p.status,
            "scheduled_at": sched_at,
            "scheduled_at_iso": sched_iso,
            "date_group": date_group,
        })

    # ── Drafts ──
    draft_result = await db.execute(
        select(Product)
        .options(selectinload(Product.images), selectinload(Product.model_ref))
        .where(Product.account_id == account_id, Product.status == "draft")
        .order_by(Product.id.desc())
        .limit(50)
    )
    drafts = []
    for p in draft_result.scalars().all():
        img = _resolve_image(p)
        model_name = None
        if p.model_ref:
            model_name = p.model_ref.name
        drafts.append({
            "product_id": p.id,
            "title": p.title,
            "price": p.price,
            "size": p.size,
            "image": img,
            "model_name": model_name,
        })

    # ── Active products with stats ──
    active_result = await db.execute(
        select(Product)
        .options(selectinload(Product.images))
        .where(
            Product.account_id == account_id,
            Product.status.in_(["active", "published", "imported"]),
        )
        .order_by(Product.published_at.desc().nullslast(), Product.id.desc())
    )
    active_products = active_result.scalars().all()

    # Stats: totals + today deltas
    act_pids = [p.id for p in active_products]
    totals_map: dict[int, tuple] = {}
    today_views_map: dict[int, int] = {}
    yesterday_views_map: dict[int, int] = {}

    if act_pids:
        totals_result = await db.execute(
            select(
                ItemStats.product_id,
                func.max(ItemStats.views).label("views_total"),
                func.max(ItemStats.contacts).label("contacts_total"),
            )
            .where(ItemStats.product_id.in_(act_pids))
            .group_by(ItemStats.product_id)
        )
        totals_map = {r.product_id: (r.views_total or 0, r.contacts_total or 0) for r in totals_result.all()}

        today_result = await db.execute(
            select(ItemStats.product_id, func.max(ItemStats.views).label("v"))
            .where(cast(ItemStats.captured_at, Date) == today, ItemStats.product_id.in_(act_pids))
            .group_by(ItemStats.product_id)
        )
        today_views_map = {r.product_id: r.v or 0 for r in today_result.all()}

        yesterday_result = await db.execute(
            select(ItemStats.product_id, func.max(ItemStats.views).label("v"))
            .where(cast(ItemStats.captured_at, Date) == yesterday, ItemStats.product_id.in_(act_pids))
            .group_by(ItemStats.product_id)
        )
        yesterday_views_map = {r.product_id: r.v or 0 for r in yesterday_result.all()}

    active_items = []
    for p in active_products:
        img = _resolve_image(p)
        vt, ct = totals_map.get(p.id, (0, 0))

        views_delta = None
        if p.id in today_views_map and p.id in yesterday_views_map:
            views_delta = max(0, today_views_map[p.id] - yesterday_views_map[p.id])

        # Marker
        if p.id in single_snapshot:
            marker = "unknown"
        elif p.id in views_5d_map:
            v5 = views_5d_map[p.id]
            if v5 is None:
                marker = "unknown"
            elif v5 < 20:
                marker = "dead"
            elif v5 <= 30:
                marker = "weak"
            else:
                marker = "alive"
        else:
            marker = "unknown"

        pub_str = None
        if p.published_at:
            pub_naive = p.published_at.replace(tzinfo=None) if p.published_at.tzinfo else p.published_at
            pub_str = pub_naive.strftime("%d.%m.%Y")

        active_items.append({
            "product_id": p.id,
            "title": p.title,
            "price": p.price,
            "image": img,
            "published_at": pub_str,
            "views_total": vt,
            "views_delta": views_delta,
            "marker": marker,
            "avito_id": p.avito_id,
        })

    # Recommendations (keep existing logic)
    models_result = await db.execute(
        select(Model)
        .options(selectinload(Model.products), selectinload(Model.photo_packs).selectinload(PhotoPack.images))
        .order_by(Model.id.desc())
    )
    all_models = models_result.scalars().unique().all()

    recommendations = []
    for md in all_models:
        has_on_account = any(
            p.account_id == account_id and p.status in ("active", "scheduled", "draft")
            for p in md.products
        )
        if has_on_account:
            continue
        pack_img = None
        for pack in md.photo_packs:
            if pack.images:
                sorted_imgs = sorted(pack.images, key=lambda x: x.sort_order)
                turl = sorted_imgs[0].url.rsplit(".", 1)
                pack_img = f"{turl[0]}_thumb.{turl[1]}" if len(turl) == 2 else sorted_imgs[0].url
                break
        label = f"{md.brand} — {md.name}" if md.brand and md.brand not in md.name else md.name
        recommendations.append({
            "model_id": md.id,
            "title": label,
            "image": pack_img,
        })

    return JSONResponse({
        "metrics": {
            "active_count": m.active_count,
            "scheduled_today": m.scheduled_today,
            "published_today": m.published_today,
            "draft_count": m.draft_count,
            "dead_count": dead_count,
        },
        "hourly_load": hourly_load,
        "scheduled": scheduled,
        "drafts": drafts,
        "active": active_items,
        "recommendations": recommendations,
    })


def _resolve_image(p: Product) -> str | None:
    """Get first image URL from product."""
    if p.images:
        sorted_imgs = sorted(p.images, key=lambda x: (not x.is_main, x.sort_order))
        return sorted_imgs[0].url
    return None


@router.get("/api/schedule/{account_id}/dashboard")
async def schedule_dashboard(account_id: int, db: AsyncSession = Depends(get_db)):
    """Dashboard data for the redesigned schedule page.

    Returns counts, dead/weak marker totals (5-day window), and a rich drafts
    list with per-draft readiness, missing fields, and alive-on-other-accounts.
    """
    cutoff_5d = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=5)

    # ── Counts per status for this account ──
    counts_result = await db.execute(
        select(
            func.count().filter(Product.status.in_(["active", "published", "imported"])).label("active_count"),
            func.count().filter(Product.status == "scheduled").label("scheduled_count"),
            func.count().filter(Product.status == "draft").label("drafts_count"),
        )
        .where(Product.account_id == account_id)
    )
    counts = counts_result.one()

    # ── Drafts for this account ──
    draft_result = await db.execute(
        select(Product)
        .options(selectinload(Product.images), selectinload(Product.model_ref))
        .where(Product.account_id == account_id, Product.status == "draft")
        .order_by(Product.id.desc())
    )
    drafts = list(draft_result.scalars().all())

    # ── Active product ids (for dead/weak counters, 5-day window) ──
    active_pids_result = await db.execute(
        select(Product.id).where(
            Product.account_id == account_id,
            Product.avito_id.isnot(None),
            Product.status.in_(["active", "published", "imported"]),
        )
    )
    active_pids = [r[0] for r in active_pids_result.all()]

    dead_count = 0
    weak_count = 0
    if active_pids:
        views_5d = await _views_5d_for(db, active_pids, cutoff_5d)
        for v in views_5d.values():
            if v is None:
                continue
            if v < 20:
                dead_count += 1
            elif v <= 30:
                weak_count += 1

    # ── alive_on_accounts: other accounts where same model_id is "alive" (v5d > 30) ──
    model_ids = [p.model_id for p in drafts if p.model_id is not None]
    alive_map: dict[int, list] = {}
    if model_ids:
        same_model_result = await db.execute(
            select(Product)
            .options(selectinload(Product.account))
            .where(
                Product.model_id.in_(model_ids),
                Product.account_id != account_id,
                Product.status.in_(["active", "published", "imported"]),
            )
        )
        same_model_products = list(same_model_result.scalars().all())
        if same_model_products:
            other_pids = [p.id for p in same_model_products]
            other_v5d = await _views_5d_for(db, other_pids, cutoff_5d)
            for p in same_model_products:
                v = other_v5d.get(p.id)
                if v is None or v <= 30:
                    continue
                alive_map.setdefault(p.model_id, []).append({
                    "account_name": p.account.name if p.account else "?",
                    "views_5d": v,
                })

    # ── Build drafts response ──
    draft_items = []
    drafts_ready = 0
    for p in drafts:
        missing = get_missing_fields(p)
        ready = not missing
        if ready:
            drafts_ready += 1

        img = _resolve_image(p) or p.image_url
        model_name = p.model_ref.name if p.model_ref else None

        draft_items.append({
            "product_id": p.id,
            "title": p.title,
            "price": p.price,
            "image": img,
            "model_id": p.model_id,
            "model_name": model_name,
            "ready": ready,
            "missing": missing,
            "alive_on_accounts": alive_map.get(p.model_id, []) if p.model_id else [],
        })

    return JSONResponse({
        "active_count": counts.active_count,
        "scheduled_count": counts.scheduled_count,
        "drafts_count": counts.drafts_count,
        "drafts_ready": drafts_ready,
        "dead_count": dead_count,
        "weak_count": weak_count,
        "drafts": draft_items,
    })


async def _views_5d_for(db: AsyncSession, pids: list[int], cutoff: datetime) -> dict[int, int | None]:
    """Compute views_5d for a set of product ids using the same window logic as
    /api/analytics/efficiency: MAX(views) in window minus MAX(views) before it;
    falls back to MAX-MIN within the window if no baseline exists; returns
    None when only a single snapshot is available (unknown marker).
    """
    if not pids:
        return {}
    window_result = await db.execute(
        select(
            ItemStats.product_id,
            func.max(ItemStats.views).label("max_views"),
            func.min(ItemStats.views).label("min_views"),
            func.count().label("cnt"),
        )
        .where(ItemStats.captured_at >= cutoff, ItemStats.product_id.in_(pids))
        .group_by(ItemStats.product_id)
    )
    window_map = {
        r.product_id: (r.max_views or 0, r.min_views or 0, r.cnt)
        for r in window_result.all()
    }
    baseline_result = await db.execute(
        select(
            ItemStats.product_id,
            func.max(ItemStats.views).label("baseline_views"),
        )
        .where(ItemStats.captured_at < cutoff, ItemStats.product_id.in_(pids))
        .group_by(ItemStats.product_id)
    )
    baseline_map = {r.product_id: r.baseline_views or 0 for r in baseline_result.all()}

    out: dict[int, int | None] = {}
    for pid, (max_v, min_v, cnt) in window_map.items():
        baseline_v = baseline_map.get(pid)
        if baseline_v is not None:
            out[pid] = max(0, max_v - baseline_v)
        elif cnt >= 2:
            out[pid] = max(0, max_v - min_v)
        else:
            out[pid] = None
    return out


@router.post("/api/schedule/{product_id}/cancel")
async def cancel_scheduled(product_id: int, db: AsyncSession = Depends(get_db)):
    product = await db.get(Product, product_id)
    if not product:
        return JSONResponse({"ok": False, "error": "Товар не найден"}, status_code=404)
    if product.status != "scheduled":
        return JSONResponse({"ok": False, "error": "Товар не в статусе scheduled"}, status_code=400)
    product.status = "draft"
    product.scheduled_at = None
    product.scheduled_account_id = None
    await db.commit()
    return JSONResponse({"ok": True})
