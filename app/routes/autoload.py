from urllib.parse import urlencode

import structlog

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.models.account import Account
from app.services.avito_client import AvitoClient
from app.services.autoload_sync import sync_ads_from_avito
from app.services.feed_importer import sync_avito_ids_from_feed

router = APIRouter(prefix="/accounts/{account_id}/autoload", tags=["autoload"])
templates = Jinja2Templates(directory="app/templates")
logger = structlog.get_logger(__name__)


def _redirect_account(account_id: int, error: str | None = None, success: str | None = None):
    url = f"/accounts/{account_id}"
    params = {}
    if error:
        params["error"] = error
    if success:
        params["success"] = success
    if params:
        url += "?" + urlencode(params)
    return RedirectResponse(url, status_code=303)


@router.post("/update-profile")
async def update_profile(
    request: Request, account_id: int, db: AsyncSession = Depends(get_db)
):
    """Update Avito autoload profile with current feed URL. Returns JSON."""
    account = await db.get(Account, account_id)
    if not account:
        return JSONResponse({"ok": False, "error": "Аккаунт не найден"}, status_code=404)

    if not account.client_id or not account.client_secret:
        return JSONResponse(
            {"ok": False, "error": f"Не заполнены credentials для аккаунта {account.name}"},
            status_code=400,
        )

    feed_url = f"{settings.BASE_URL}/feeds/{account.feed_token}.xml"
    client = AvitoClient(account, db)
    try:
        result = await client.update_profile(feed_url, feed_name=account.name)
        logger.info("Profile updated for account %s: %s", account_id, result)
        # v2 API returns feeds_data array instead of upload_url
        feeds_data = result.get("feeds_data") or []
        active_feed_url = feeds_data[0]["feed_url"] if feeds_data else feed_url
        return JSONResponse({
            "ok": True,
            "feed_url": active_feed_url,
            "profile": result,
        })
    except Exception as e:
        logger.exception("Profile update failed for account %s: %s", account_id, e)
        return JSONResponse({"ok": False, "error": "Ошибка обновления профиля Avito"}, status_code=502)
    finally:
        await client.close()


@router.post("/upload")
async def trigger_upload(
    request: Request, account_id: int, db: AsyncSession = Depends(get_db)
):
    account = await db.get(Account, account_id)
    if not account:
        return HTMLResponse("Аккаунт не найден", status_code=404)

    client = AvitoClient(account, db)
    try:
        result = await client.upload()
        logger.info("Upload triggered for account %s: %s", account_id, result)
        return _redirect_account(account_id, success="Upload запущен")
    except Exception as e:
        logger.exception("Upload failed for account %s: %s", account_id, e)
        return _redirect_account(account_id, error="Ошибка загрузки фида")
    finally:
        await client.close()


@router.post("/sync-ads")
async def sync_ads(account_id: int, db: AsyncSession = Depends(get_db)):
    """Sync existing autoload ads from Avito into products table."""
    account = await db.get(Account, account_id)
    if not account:
        return JSONResponse({"ok": False, "error": "Аккаунт не найден"}, status_code=404)

    if not account.client_id or not account.client_secret:
        return JSONResponse(
            {"ok": False, "error": f"Не заполнены credentials для аккаунта {account.name}"},
            status_code=400,
        )

    result = await sync_ads_from_avito(account.id, db)
    if result.get("error"):
        return JSONResponse({"ok": False, "error": result["error"]}, status_code=502)

    return JSONResponse({
        "ok": True,
        "created": result["created"],
        "synced": result["synced"],
        "skipped": result["skipped"],
        "avito_ids_filled": result.get("avito_ids_filled", 0),
        "pass3_matched": result.get("pass3_matched", 0),
        "pass3_created": result.get("pass3_created", 0),
    })


@router.post("/sync-from-feed")
async def sync_from_feed(account_id: int, db: AsyncSession = Depends(get_db)):
    """Download Avito's current XML feed and import avito_ids into our DB."""
    account = await db.get(Account, account_id)
    if not account:
        return JSONResponse({"ok": False, "error": "Аккаунт не найден"}, status_code=404)

    if not account.client_id or not account.client_secret:
        return JSONResponse(
            {"ok": False, "error": f"Не заполнены credentials для аккаунта {account.name}"},
            status_code=400,
        )

    result = await sync_avito_ids_from_feed(account.id, db)
    if result.get("error"):
        return JSONResponse({
            "ok": False,
            "error": result["error"],
            "matched": result.get("matched", 0),
            "created": result.get("created", 0),
            "skipped": result.get("skipped", 0),
            "total_in_feed": result.get("total_in_feed", 0),
        }, status_code=502)

    return JSONResponse({
        "ok": True,
        "matched": result["matched"],
        "created": result["created"],
        "skipped": result["skipped"],
        "total_in_feed": result["total_in_feed"],
        "error": None,
    })
