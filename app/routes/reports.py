from urllib.parse import urlencode

import structlog

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.models.account import Account
from app.models.autoload_report import AutoloadReport
from app.models.autoload_report_item import AutoloadReportItem
from app.services.avito_client import AvitoClient

router = APIRouter(prefix="/reports", tags=["reports"])
templates = Jinja2Templates(directory="app/templates")
logger = structlog.get_logger(__name__)


@router.get("", response_class=HTMLResponse)
async def reports_list(request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AutoloadReport)
        .options(selectinload(AutoloadReport.account))
        .order_by(AutoloadReport.created_at.desc())
        .limit(50)
    )
    reports = result.scalars().all()
    return templates.TemplateResponse("reports/list.html", {"request": request, "reports": reports, "page_title": "Отчёты"})


@router.get("/{report_id}", response_class=HTMLResponse)
async def report_detail(request: Request, report_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AutoloadReport)
        .options(selectinload(AutoloadReport.account), selectinload(AutoloadReport.items))
        .where(AutoloadReport.id == report_id)
    )
    report = result.scalar_one_or_none()
    if not report:
        return HTMLResponse("Отчет не найден", status_code=404)
    return templates.TemplateResponse("reports/detail.html", {"request": request, "report": report, "page_title": "Отчёты"})


@router.post("/fetch/{account_id}")
async def fetch_reports(
    request: Request, account_id: int, db: AsyncSession = Depends(get_db)
):
    account = await db.get(Account, account_id)
    if not account:
        return HTMLResponse("Аккаунт не найден", status_code=404)

    client = AvitoClient(account, db)
    try:
        data = await client.get_reports()
        for report_data in data.get("reports", []):
            avito_id = str(report_data.get("id", ""))

            existing = await db.execute(
                select(AutoloadReport).where(AutoloadReport.avito_report_id == avito_id)
            )
            if existing.scalar_one_or_none():
                continue

            report = AutoloadReport(
                account_id=account_id,
                avito_report_id=avito_id,
                status=report_data.get("status", "unknown"),
                total_ads=report_data.get("total_ads", 0),
                applied_ads=report_data.get("applied_ads", 0),
                declined_ads=report_data.get("declined_ads", 0),
                extra=report_data,
            )
            db.add(report)
            await db.flush()

            # Fetch items for this report
            try:
                items_data = await client.get_report_items(avito_id)
                for item_data in items_data.get("items", []):
                    item = AutoloadReportItem(
                        report_id=report.id,
                        ad_id=str(item_data.get("ad_id", "")),
                        avito_id=str(item_data.get("avito_id", "")),
                        url=item_data.get("url"),
                        status=item_data.get("status", "unknown"),
                        messages=item_data.get("messages"),
                        error_text=item_data.get("error"),
                    )
                    db.add(item)
            except Exception as e:
                logger.warning("Failed to fetch items for report %s: %s", avito_id, e)

        await db.commit()
        return RedirectResponse("/reports?" + urlencode({"success": "Отчёты загружены"}), status_code=303)
    except Exception as e:
        logger.error("Failed to fetch reports for account %s: %s", account_id, e)
        return RedirectResponse("/reports?" + urlencode({"error": f"Ошибка загрузки отчётов: {e}"}), status_code=303)
    finally:
        await client.close()
