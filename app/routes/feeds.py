import os

import aiofiles
import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db import get_db, utc_now
from app.models.account import Account
from app.models.autoload_report import AutoloadReport
from app.models.autoload_report_item import AutoloadReportItem
from app.models.feed_export import FeedExport
from app.services.avito_client import AvitoClient
from app.services.feed_generator import generate_feed

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["feeds"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/feeds", response_class=HTMLResponse)
async def feeds_page(request: Request, db: AsyncSession = Depends(get_db)):
    accs = await db.execute(select(Account).order_by(Account.id))
    accounts = accs.scalars().all()

    exports_result = await db.execute(
        select(FeedExport)
        .options(selectinload(FeedExport.account))
        .order_by(FeedExport.created_at.desc())
        .limit(50)
    )
    exports = exports_result.scalars().all()

    return templates.TemplateResponse("feeds/list.html", {"page_title": "Фиды",
        "request": request,
        "accounts": accounts,
        "exports": exports,
        "base_url": settings.BASE_URL,
    })


@router.post("/feeds/{account_id}/generate")
async def generate_feed_endpoint(
    request: Request, account_id: int, db: AsyncSession = Depends(get_db)
):
    try:
        filepath, count = await generate_feed(account_id, db)
    except ValueError as e:
        return HTMLResponse(str(e), status_code=404)
    return RedirectResponse("/feeds", status_code=303)


@router.get("/feeds/{token}.xml")
async def serve_feed(token: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Account).where(Account.feed_token == token)
    )
    account = result.scalar_one_or_none()
    if not account:
        return Response("Feed not found", status_code=404)
    filepath = os.path.join(settings.FEEDS_DIR, f"{account.id}.xml")
    if not os.path.exists(filepath):
        return Response("Feed not found", status_code=404)
    async with aiofiles.open(filepath, "rb") as f:
        content = await f.read()
    return Response(content=content, media_type="application/xml")


@router.delete("/feeds/{feed_id}")
async def delete_feed(feed_id: int, db: AsyncSession = Depends(get_db)):
    export = await db.get(FeedExport, feed_id)
    if not export:
        return JSONResponse({"ok": False, "error": "Фид не найден"}, status_code=404)

    # Delete XML file from disk
    if export.file_path:
        safe_path = os.path.normpath(export.file_path)
        feeds_root = os.path.normpath(settings.FEEDS_DIR)
        if safe_path.startswith(feeds_root) and os.path.exists(safe_path):
            try:
                os.remove(safe_path)
            except OSError:
                pass

    await db.delete(export)
    await db.commit()
    return JSONResponse({"ok": True})


@router.post("/feeds/{feed_id}/upload")
async def upload_feed_to_avito(
    feed_id: int, db: AsyncSession = Depends(get_db)
):
    """Upload a generated XML feed to Avito Autoload API."""
    result = await db.execute(
        select(FeedExport)
        .options(selectinload(FeedExport.account))
        .where(FeedExport.id == feed_id)
    )
    export = result.scalar_one_or_none()
    if not export:
        return JSONResponse({"ok": False, "error": "Фид не найден"}, status_code=404)

    account = export.account
    if not account:
        return JSONResponse(
            {"ok": False, "error": "Аккаунт не привязан к фиду"},
            status_code=400,
        )
    if not account.client_id or not account.client_secret:
        return JSONResponse(
            {"ok": False, "error": f"Не заполнены credentials для аккаунта {account.name}"},
            status_code=400,
        )

    if not os.path.exists(export.file_path):
        return JSONResponse(
            {"ok": False, "error": "XML-файл не найден на диске"},
            status_code=404,
        )

    async with aiofiles.open(export.file_path, "rb") as f:
        xml_bytes = await f.read()

    filename = os.path.basename(export.file_path)

    client = AvitoClient(account, db)
    try:
        avito_response = await client.upload_feed(xml_bytes, filename)
    except Exception as e:
        error_msg = str(e)
        logger.error("Avito upload failed for feed %d: %s", feed_id, error_msg)

        if "401" in error_msg or "unauthorized" in error_msg.lower():
            export.status = "token_expired"
            export.upload_response = {"error": error_msg}
            await db.commit()
            return JSONResponse(
                {
                    "ok": False,
                    "error": f"Токен истёк, обновите credentials для аккаунта {account.name}",
                },
                status_code=401,
            )

        export.status = "upload_error"
        export.upload_response = {"error": error_msg}
        await db.commit()
        return JSONResponse({"ok": False, "error": "Ошибка загрузки фида в Avito"}, status_code=502)
    finally:
        await client.close()

    # Avito returns 200 but with {"error": {...}} on rate-limit / validation errors
    avito_error = avito_response.get("error")
    if avito_error:
        error_msg = avito_error.get("message", str(avito_error)) if isinstance(avito_error, dict) else str(avito_error)
        export.status = "upload_error"
        export.upload_response = avito_response
        await db.commit()
        logger.warning("Avito upload rejected for feed %d: %s", feed_id, error_msg)
        return JSONResponse(
            {"ok": False, "error": error_msg},
            status_code=422,
        )

    export.status = "uploaded"
    export.uploaded_at = utc_now()
    export.upload_response = avito_response
    await db.commit()

    logger.info("Feed %d uploaded to Avito: %s", feed_id, avito_response)
    return JSONResponse({"ok": True, "avito_response": avito_response})


@router.get("/feeds/{feed_id}/report")
async def get_feed_report(feed_id: int, db: AsyncSession = Depends(get_db)):
    """Fetch the latest Avito autoload report for this feed's account."""
    result = await db.execute(
        select(FeedExport)
        .options(selectinload(FeedExport.account))
        .where(FeedExport.id == feed_id)
    )
    export = result.scalar_one_or_none()
    if not export:
        return JSONResponse({"ok": False, "error": "Фид не найден"}, status_code=404)

    account = export.account
    if not account or not account.client_id or not account.client_secret:
        return JSONResponse(
            {"ok": False, "error": "Нет credentials для аккаунта"},
            status_code=400,
        )

    client = AvitoClient(account, db)
    try:
        # Get list of reports, find the latest one
        reports_data = await client.get_reports()
        reports = reports_data.get("reports", [])
        if not reports:
            return JSONResponse({
                "ok": True,
                "status": "pending",
                "message": "Avito ещё обрабатывает фид, попробуйте через несколько минут",
            })

        # Find the report closest to this feed's upload time
        target_report = None
        if export.uploaded_at:
            upload_ts = export.uploaded_at.isoformat() + "Z" if export.uploaded_at.tzinfo is None else export.uploaded_at.isoformat()
            for r in reports:
                started = r.get("started_at", "")
                if started and started >= upload_ts[:16]:
                    target_report = r
                    break
        # Fallback: latest report
        if not target_report:
            target_report = reports[0]

        report_id = target_report["id"]
        report_status = target_report.get("status", "unknown")

        # Fetch report details
        detail = await client.get_report(report_id)

        # Fetch items if report has finished
        items_data = []
        section_stats = detail.get("section_stats", {})
        events = detail.get("events") or []

        if report_status not in ("in_progress", "pending"):
            try:
                items_resp = await client.get_report_items(report_id)
                items_data = items_resp.get("items") or []
            except Exception:
                pass

        # Save to autoload_reports
        existing = await db.execute(
            select(AutoloadReport).where(
                AutoloadReport.avito_report_id == str(report_id)
            )
        )
        report_row = existing.scalar_one_or_none()
        if not report_row:
            report_row = AutoloadReport(
                account_id=account.id,
                avito_report_id=str(report_id),
                status=report_status,
                total_ads=section_stats.get("count", 0),
                extra=detail,
            )
            db.add(report_row)
            await db.flush()
        else:
            report_row.status = report_status
            report_row.total_ads = section_stats.get("count", 0)
            report_row.extra = detail

        # Count applied/declined from items
        applied = sum(1 for i in items_data if i.get("status") in ("active", "old"))
        declined = sum(1 for i in items_data if i.get("status") in ("rejected", "error"))
        report_row.applied_ads = applied
        report_row.declined_ads = declined

        # Save items — clear old items first to avoid duplicates
        if items_data:
            await db.execute(
                delete(AutoloadReportItem).where(
                    AutoloadReportItem.report_id == report_row.id
                )
            )
            for item in items_data:
                item_row = AutoloadReportItem(
                    report_id=report_row.id,
                    ad_id=str(item.get("ad_id", "")),
                    avito_id=str(item.get("avito_id", "")),
                    url=item.get("url"),
                    status=item.get("status", "unknown"),
                    messages=item.get("messages"),
                    error_text="; ".join(
                        m.get("description", "") for m in (item.get("messages") or [])
                        if m.get("type") == "error"
                    ) or None,
                )
                db.add(item_row)

        await db.commit()

        # Send Telegram notification if there are declined ads
        if declined > 0:
            from app.services.telegram_notify import notify_declined
            await notify_declined(
                account_name=account.name,
                declined_ads=declined,
                total_ads=report_row.total_ads,
                report_id=report_row.id,
            )

        # Build response
        error_items = []
        for item in items_data:
            messages = item.get("messages") or []
            errors = [m.get("description", "") for m in messages if m.get("type") == "error"]
            warnings = [m.get("description", "") for m in messages if m.get("type") == "warning"]
            if errors or warnings:
                error_items.append({
                    "ad_id": item.get("ad_id"),
                    "avito_id": item.get("avito_id"),
                    "url": item.get("url"),
                    "status": item.get("status"),
                    "errors": errors,
                    "warnings": warnings,
                })

        # Events from the report (feed-level errors like "couldn't download file")
        event_errors = [
            {"code": e.get("code"), "description": e.get("description")}
            for e in events if e.get("type") == "error"
        ]

        return JSONResponse({
            "ok": True,
            "status": report_status,
            "report_id": report_id,
            "started_at": target_report.get("started_at"),
            "finished_at": target_report.get("finished_at") or None,
            "feed_url": (detail.get("feeds_urls") or [{}])[0].get("url") or detail.get("feed_url"),
            "stats": {
                "total": section_stats.get("count", 0),
                "applied": applied,
                "declined": declined,
            },
            "events": event_errors,
            "error_items": error_items[:50],
            "message": (
                "Avito ещё обрабатывает фид, попробуйте через несколько минут"
                if report_status in ("in_progress", "pending") else None
            ),
        })

    except Exception as e:
        logger.exception("Failed to fetch report for feed %d: %s", feed_id, e)
        return JSONResponse(
            {"ok": False, "error": "Внутренняя ошибка при получении отчёта"},
            status_code=502,
        )
    finally:
        await client.close()
