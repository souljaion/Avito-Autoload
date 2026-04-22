import hashlib
import os
import tempfile

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.account import Account
from app.models.product import Product
from app.services.sync_from_avito_export import sync_from_excel

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory="app/templates")

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


@router.get("/avito-sync", response_class=HTMLResponse)
async def avito_sync_page(request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Account).order_by(Account.id))
    accounts = result.scalars().all()

    counts = {}
    for acc in accounts:
        r = await db.execute(
            select(func.count()).select_from(Product).where(Product.account_id == acc.id)
        )
        counts[acc.id] = r.scalar() or 0

    return templates.TemplateResponse("admin/avito_sync.html", {
        "request": request,
        "accounts": accounts,
        "counts": counts,
        "page_title": "Синхронизация с Авито",
        "report": None,
        "preview_hash": None,
    })


@router.post("/avito-sync/preview", response_class=HTMLResponse)
async def avito_sync_preview(
    request: Request,
    account_id: int = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    if not file.filename or not file.filename.endswith(".xlsx"):
        raise HTTPException(400, "Файл должен быть .xlsx")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(400, "Файл слишком большой (макс 50 MB)")

    file_hash = hashlib.md5(content).hexdigest()

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        report = await sync_from_excel(tmp_path, account_id, db, dry_run=True)
    finally:
        os.unlink(tmp_path)

    result = await db.execute(select(Account).order_by(Account.id))
    accounts = result.scalars().all()
    counts = {}
    for acc in accounts:
        r = await db.execute(
            select(func.count()).select_from(Product).where(Product.account_id == acc.id)
        )
        counts[acc.id] = r.scalar() or 0

    return templates.TemplateResponse("admin/avito_sync.html", {
        "request": request,
        "accounts": accounts,
        "counts": counts,
        "page_title": "Синхронизация с Авито",
        "report": report,
        "preview_hash": file_hash,
        "preview_account_id": account_id,
    })


@router.post("/avito-sync/apply", response_class=HTMLResponse)
async def avito_sync_apply(
    request: Request,
    account_id: int = Form(...),
    preview_hash: str = Form(""),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    if not preview_hash:
        raise HTTPException(400, "Сначала выполните предпросмотр (preview)")

    if not file.filename or not file.filename.endswith(".xlsx"):
        raise HTTPException(400, "Файл должен быть .xlsx")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(400, "Файл слишком большой (макс 50 MB)")

    file_hash = hashlib.md5(content).hexdigest()
    if file_hash != preview_hash:
        raise HTTPException(400, "Файл изменился после предпросмотра. Повторите preview.")

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        report = await sync_from_excel(tmp_path, account_id, db, dry_run=False)
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    finally:
        os.unlink(tmp_path)

    result = await db.execute(select(Account).order_by(Account.id))
    accounts = result.scalars().all()
    counts = {}
    for acc in accounts:
        r = await db.execute(
            select(func.count()).select_from(Product).where(Product.account_id == acc.id)
        )
        counts[acc.id] = r.scalar() or 0

    return templates.TemplateResponse("admin/avito_sync.html", {
        "request": request,
        "accounts": accounts,
        "counts": counts,
        "page_title": "Синхронизация с Авито",
        "report": report,
        "applied": True,
        "preview_hash": None,
    })
