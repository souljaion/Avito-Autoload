from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func, exists
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db import get_db
from app.models.account import Account
from app.models.autoload_report import AutoloadReport
from app.models.autoload_report_item import AutoloadReportItem
from app.models.feed_export import FeedExport
from app.models.item_stats import ItemStats
from app.models.listing import Listing
from app.models.model import Model
from app.models.product import Product

MSK = ZoneInfo("Europe/Moscow")

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory="app/templates")


def _product_problems(p, has_images: bool) -> list[str]:
    """Return list of problems preventing product from being feed-ready."""
    problems = []
    if not p.description:
        problems.append("нет описания")
    if p.price is None:
        problems.append("нет цены")
    if not p.category or not p.goods_type:
        problems.append("не заполнена категория")
    from app.catalog import requires_subtype
    if not p.subcategory:
        problems.append("не заполнен подтип")
    elif not p.goods_subtype and requires_subtype(p.category, p.goods_type, p.subcategory):
        problems.append("не заполнен подтип")
    if not has_images:
        problems.append("нет фото")
    return problems


@router.get("/api/dashboard/command-center")
async def command_center(db: AsyncSession = Depends(get_db)):
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)

    # ── Block 1: requires_attention ──
    attention = []

    # Models without active ads on any account
    models_result = await db.execute(
        select(Model).options(selectinload(Model.products)).order_by(Model.id.desc())
    )
    all_models = models_result.scalars().unique().all()
    for m in all_models:
        has_active = any(
            p.status in ("active", "published", "scheduled")
            for p in m.products
        )
        if not has_active:
            attention.append({
                "type": "model_no_ads",
                "model_id": m.id,
                "title": f"{m.brand} — {m.name}" if m.brand and m.brand not in m.name else m.name,
                "message": "Нигде не выложено",
            })

    # Declined ads (last 7 days)
    week_ago = now - timedelta(days=7)
    declined_result = await db.execute(
        select(AutoloadReportItem)
        .join(AutoloadReport)
        .options(selectinload(AutoloadReportItem.report).selectinload(AutoloadReport.account))
        .where(
            AutoloadReportItem.status == "declined",
            AutoloadReport.created_at >= week_ago,
        )
        .order_by(AutoloadReportItem.id.desc())
        .limit(5)
    )
    for item in declined_result.scalars().all():
        acc_name = item.report.account.name if item.report and item.report.account else "?"
        attention.append({
            "type": "declined",
            "ad_id": item.ad_id,
            "avito_id": item.avito_id,
            "account_name": acc_name,
            "message": item.error_text or "Отклонено Авито",
        })

    # Dead ads (< 20 views delta in 5 days)
    cutoff_5d = datetime.utcnow() - timedelta(days=5)
    window_stmt = select(
        ItemStats.product_id,
        func.max(ItemStats.views).label("mx"),
        func.min(ItemStats.views).label("mn"),
    ).where(ItemStats.captured_at >= cutoff_5d).group_by(ItemStats.product_id)
    window_result = await db.execute(window_stmt)
    window_map = {r.product_id: (r.mx or 0, r.mn or 0) for r in window_result.all()}

    baseline_stmt = select(
        ItemStats.product_id, func.max(ItemStats.views).label("bv")
    ).where(ItemStats.captured_at < cutoff_5d).group_by(ItemStats.product_id)
    baseline_result = await db.execute(baseline_stmt)
    baseline_map = {r.product_id: r.bv or 0 for r in baseline_result.all()}

    views_map = {}
    for pid, (mx, mn) in window_map.items():
        bv = baseline_map.get(pid)
        views_map[pid] = max(0, mx - bv) if bv is not None else max(0, mx - mn)

    dead_products_result = await db.execute(
        select(Product)
        .options(selectinload(Product.account))
        .where(
            Product.avito_id.isnot(None),
            Product.status.in_(["active", "published"]),
        )
    )
    for p in dead_products_result.scalars().all():
        if p.id in views_map and views_map[p.id] < 20:
            attention.append({
                "type": "dead",
                "product_id": p.id,
                "title": p.title,
                "account_name": p.account.name if p.account else "?",
                "message": f"{views_map[p.id]} просмотров за 5 дней",
            })

    # ── Block 2: scheduled_today ──
    scheduled_result = await db.execute(
        select(Product)
        .options(selectinload(Product.account))
        .where(
            Product.status == "scheduled",
            Product.scheduled_at >= today_start,
            Product.scheduled_at < today_end,
        )
        .order_by(Product.scheduled_at.asc())
    )
    scheduled_today = []
    for p in scheduled_result.scalars().all():
        msk_time = p.scheduled_at.replace(tzinfo=timezone.utc).astimezone(MSK) if p.scheduled_at else now.replace(tzinfo=timezone.utc).astimezone(MSK)
        sync_min = p.account.avito_sync_minute if p.account else None
        if sync_min is not None:
            sh, sm = msk_time.hour, msk_time.minute
            appear_h = sh if sm <= sync_min else (sh + 1) % 24
            display_time = f"~{appear_h:02d}:{sync_min:02d}"
        else:
            display_time = msk_time.strftime("%H:%M")
        scheduled_today.append({
            "product_id": p.id,
            "title": p.title,
            "account_name": p.account.name if p.account else "?",
            "display_time": display_time,
        })

    # ── Block 3: stats ──
    active_count_result = await db.execute(
        select(func.count()).where(Product.status.in_(["active", "published"]))
    )
    active_count = active_count_result.scalar() or 0

    active_accounts_result = await db.execute(
        select(func.count(func.distinct(Product.account_id))).where(
            Product.status.in_(["active", "published"]),
            Product.account_id.isnot(None),
        )
    )
    active_accounts = active_accounts_result.scalar() or 0

    total_accounts_result = await db.execute(select(func.count()).select_from(Account))
    total_accounts = total_accounts_result.scalar() or 0

    total_models = len(all_models)

    # Last sync time
    last_sync_result = await db.execute(select(func.max(ItemStats.captured_at)))
    last_sync_val = last_sync_result.scalar()
    last_sync_str = None
    sync_stale = False
    if last_sync_val:
        last_sync_msk = last_sync_val.replace(tzinfo=timezone.utc).astimezone(MSK)
        last_sync_str = last_sync_msk.strftime("%d.%m.%Y %H:%M")
        hours_ago = (datetime.utcnow() - last_sync_val).total_seconds() / 3600
        sync_stale = hours_ago > 4

    # ── Block 4: recommendations ──
    recommendations = []
    accs_result = await db.execute(select(Account).order_by(Account.name))
    all_accounts = accs_result.scalars().all()
    acc_ids = {a.id for a in all_accounts}
    acc_names = {a.id: a.name for a in all_accounts}

    for m in all_models:
        present_acc_ids = {
            p.account_id for p in m.products
            if p.status in ("active", "published", "scheduled", "draft") and p.account_id
        }
        if 0 < len(present_acc_ids) < len(acc_ids):
            missing = acc_ids - present_acc_ids
            for mid in list(missing)[:1]:
                model_label = f"{m.brand} — {m.name}" if m.brand and m.brand not in m.name else m.name
                recommendations.append({
                    "type": "add_model",
                    "message": f"Добавь {model_label} на {acc_names[mid]}",
                    "model_id": m.id,
                })
        if len(recommendations) >= 5:
            break

    # Dead product recommendations — fetch titles for dead products
    if len(recommendations) < 5:
        dead_ids = [pid for pid, v in views_map.items() if v < 20]
        if dead_ids:
            dead_result = await db.execute(
                select(Product.id, Product.title).where(Product.id.in_(dead_ids[:5]))
            )
            dead_titles = {r.id: r.title for r in dead_result.all()}
            for p_id in dead_ids:
                if len(recommendations) >= 5:
                    break
                title = dead_titles.get(p_id, f"#{p_id}")
                short = title[:40] + "..." if len(title) > 40 else title
                recommendations.append({
                    "type": "repost",
                    "message": f"Перевыложи {short} — < 20 просмотров за 5 дней",
                    "product_id": p_id,
                })

    if not scheduled_today and len(recommendations) < 5:
        recommendations.append({
            "type": "no_scheduled",
            "message": "Сегодня нет запланированных выкладок",
        })

    return JSONResponse({
        "attention": attention[:10],
        "scheduled_today": scheduled_today,
        "stats": {
            "active_ads": active_count,
            "active_accounts": active_accounts,
            "total_accounts": total_accounts,
            "total_models": total_models,
            "dead_ads": sum(1 for v in views_map.values() if v is not None and v < 20),
            "weak_ads": sum(1 for v in views_map.values() if v is not None and 20 <= v <= 30),
            "problem_ads": sum(1 for v in views_map.values() if v is not None and v <= 30),
            "last_sync": last_sync_str,
            "sync_stale": sync_stale,
        },
        "recommendations": recommendations[:5],
    })


@router.get("/api/dashboard")
async def dashboard_data(db: AsyncSession = Depends(get_db)):
    # ── Products stats (aggregate instead of loading all) ──
    counts_result = await db.execute(
        select(Product.status, func.count()).group_by(Product.status)
    )
    status_counts = {row[0]: row[1] for row in counts_result.all()}
    total = sum(status_counts.values())
    active = status_counts.get("active", 0)
    draft = status_counts.get("draft", 0) + status_counts.get("imported", 0)

    # ── Problem products (limited query with images) ──
    # Products that might have problems — load a reasonable batch
    candidates_result = await db.execute(
        select(Product)
        .options(selectinload(Product.images))
        .where(Product.status.in_(["active", "published", "draft", "imported"]))
        .order_by(Product.id.desc())
        .limit(50)
    )
    problem_products = []
    for p in candidates_result.scalars().all():
        has_images = bool(p.images)
        problems = _product_problems(p, has_images)
        if problems:
            problem_products.append({
                "id": p.id,
                "title": p.title,
                "status": p.status,
                "problems": problems,
            })
            if len(problem_products) >= 5:
                break

    # ── Latest products (DB-side sort + limit) ──
    latest_result = await db.execute(
        select(Product).order_by(Product.id.desc()).limit(5)
    )
    latest_products_data = [
        {
            "id": p.id,
            "title": p.title,
            "status": p.status,
            "price": p.price,
            "created_at": p.created_at.strftime("%d.%m.%Y %H:%M") if p.created_at else None,
        }
        for p in latest_result.scalars().all()
    ]

    # ── Accounts with feed info ──
    accounts = (await db.execute(select(Account).order_by(Account.id))).scalars().all()

    # Latest generated feed per account: DISTINCT ON
    latest_gen_result = await db.execute(
        select(FeedExport)
        .distinct(FeedExport.account_id)
        .order_by(FeedExport.account_id, FeedExport.created_at.desc())
    )
    latest_gen_by_acc: dict[int, FeedExport] = {
        exp.account_id: exp for exp in latest_gen_result.scalars().all()
    }

    # Latest uploaded feed per account: DISTINCT ON with filter
    latest_upload_result = await db.execute(
        select(FeedExport)
        .where(FeedExport.uploaded_at.isnot(None))
        .distinct(FeedExport.account_id)
        .order_by(FeedExport.account_id, FeedExport.created_at.desc())
    )
    latest_upload_by_acc: dict[int, FeedExport] = {
        exp.account_id: exp for exp in latest_upload_result.scalars().all()
    }

    accounts_data = []
    for acc in accounts:
        latest_gen = latest_gen_by_acc.get(acc.id)
        latest_upload = latest_upload_by_acc.get(acc.id)

        accounts_data.append({
            "id": acc.id,
            "name": acc.name,
            "feed_url": f"{settings.BASE_URL}/feeds/{acc.feed_token}.xml",
            "last_generated": latest_gen.created_at.strftime("%d.%m.%Y %H:%M") if latest_gen else None,
            "last_generated_id": latest_gen.id if latest_gen else None,
            "last_generated_count": latest_gen.products_count if latest_gen else 0,
            "last_upload_at": latest_upload.uploaded_at.strftime("%d.%m.%Y %H:%M") if latest_upload and latest_upload.uploaded_at else None,
            "last_upload_status": latest_upload.status if latest_upload else None,
            "last_upload_id": latest_upload.id if latest_upload else None,
        })

    # ── Last upload overall ──
    last_upload = (await db.execute(
        select(FeedExport)
        .where(FeedExport.status.in_(["uploaded", "upload_error", "token_expired"]))
        .order_by(FeedExport.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()

    last_upload_data = None
    if last_upload:
        last_upload_data = {
            "id": last_upload.id,
            "status": last_upload.status,
            "uploaded_at": last_upload.uploaded_at.strftime("%d.%m.%Y %H:%M") if last_upload.uploaded_at else None,
            "created_at": last_upload.created_at.strftime("%d.%m.%Y %H:%M") if last_upload.created_at else None,
        }

    # ── Latest reports ──
    reports_result = await db.execute(
        select(AutoloadReport)
        .options(selectinload(AutoloadReport.account))
        .order_by(AutoloadReport.created_at.desc())
        .limit(3)
    )
    reports = reports_result.scalars().all()
    reports_data = [
        {
            "id": r.id,
            "account_name": r.account.name if r.account else f"#{r.account_id}",
            "status": r.status,
            "total_ads": r.total_ads,
            "applied_ads": r.applied_ads,
            "declined_ads": r.declined_ads,
            "created_at": r.created_at.strftime("%d.%m.%Y %H:%M") if r.created_at else None,
        }
        for r in reports
    ]

    last_report_summary = None
    if reports:
        r = reports[0]
        last_report_summary = {
            "total": r.total_ads,
            "applied": r.applied_ads,
            "declined": r.declined_ads,
            "status": r.status,
        }

    # ── Upcoming scheduled products ──
    scheduled_result = await db.execute(
        select(Product)
        .options(selectinload(Product.account))
        .where(Product.status == "scheduled")
        .order_by(Product.scheduled_at.asc())
        .limit(5)
    )
    scheduled_products = [
        {
            "id": p.id,
            "title": p.title,
            "account": p.account.name if p.account else None,
            "scheduled_at": p.scheduled_at.strftime("%d.%m.%Y %H:%M") if p.scheduled_at else None,
        }
        for p in scheduled_result.scalars().all()
    ]

    return JSONResponse({
        "products": {"total": total, "active": active, "draft": draft},
        "last_upload": last_upload_data,
        "last_report": last_report_summary,
        "accounts": accounts_data,
        "latest_products": latest_products_data,
        "reports": reports_data,
        "problem_products": problem_products,
        "scheduled": scheduled_products,
    })


@router.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request, "page_title": "Командный центр"})
