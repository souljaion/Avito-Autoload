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

    feed_url = f"{settings.BASE_URL}/feeds/{account_id}.xml"
    client = AvitoClient(account, db)
    try:
        result = await client.update_profile(feed_url)
        logger.info("Profile updated for account %s: %s", account_id, result)
        return JSONResponse({
            "ok": True,
            "feed_url": result.get("upload_url", feed_url),
            "profile": result,
        })
    except Exception as e:
        logger.error("Profile update failed for account %s: %s", account_id, e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=502)
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
        logger.error("Upload failed for account %s: %s", account_id, e)
        return _redirect_account(account_id, error=f"Ошибка upload: {e}")
    finally:
        await client.close()
