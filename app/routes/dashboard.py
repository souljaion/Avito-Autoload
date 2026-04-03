from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db import get_db
from app.models.account import Account
from app.models.autoload_report import AutoloadReport
from app.models.feed_export import FeedExport
from app.models.product import Product

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
    if not p.subcategory or not p.goods_subtype:
        problems.append("не заполнен подтип")
    if not has_images:
        problems.append("нет фото")
    return problems


@router.get("/api/dashboard")
async def dashboard_data(db: AsyncSession = Depends(get_db)):
    # ── Products stats ──
    all_products = (await db.execute(
        select(Product).options(selectinload(Product.images))
    )).scalars().all()

    total = len(all_products)
    active = sum(1 for p in all_products if p.status == "active")
    draft = sum(1 for p in all_products if p.status in ("draft", "imported"))

    # ── Problem products (active but not feed-ready, or draft with issues) ──
    problem_products = []
    for p in all_products:
        has_images = bool(p.images)
        problems = _product_problems(p, has_images)
        if problems and len(problem_products) < 5:
            problem_products.append({
                "id": p.id,
                "title": p.title,
                "status": p.status,
                "problems": problems,
            })

    # ── Latest products ──
    latest_products = sorted(all_products, key=lambda p: p.id, reverse=True)[:5]
    latest_products_data = [
        {
            "id": p.id,
            "title": p.title,
            "status": p.status,
            "price": p.price,
            "created_at": p.created_at.strftime("%d.%m.%Y %H:%M") if p.created_at else None,
        }
        for p in latest_products
    ]

    # ── Accounts with feed info (batch load to avoid N+1) ──
    accounts = (await db.execute(select(Account).order_by(Account.id))).scalars().all()

    # Load all feed exports at once instead of per-account queries
    all_exports_result = await db.execute(
        select(FeedExport).order_by(FeedExport.created_at.desc())
    )
    all_exports = all_exports_result.scalars().all()

    # Group by account
    latest_gen_by_acc: dict[int, FeedExport] = {}
    latest_upload_by_acc: dict[int, FeedExport] = {}
    for exp in all_exports:
        if exp.account_id not in latest_gen_by_acc:
            latest_gen_by_acc[exp.account_id] = exp
        if exp.uploaded_at and exp.account_id not in latest_upload_by_acc:
            latest_upload_by_acc[exp.account_id] = exp

    accounts_data = []
    for acc in accounts:
        latest_gen = latest_gen_by_acc.get(acc.id)
        latest_upload = latest_upload_by_acc.get(acc.id)

        accounts_data.append({
            "id": acc.id,
            "name": acc.name,
            "feed_url": f"{settings.BASE_URL}/feeds/{acc.id}.xml",
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
    return templates.TemplateResponse("dashboard.html", {"request": request})
