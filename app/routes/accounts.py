from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.crypto import encrypt, decrypt
from app.db import get_db
from app.models.account import Account
from app.models.account_description_template import AccountDescriptionTemplate
from app.services.avito_client import AvitoClient
from app.services.excel_importer import import_avito_excel, InvalidExcelError

router = APIRouter(prefix="/accounts", tags=["accounts"])
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
async def account_list(request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Account).order_by(Account.id.desc()))
    accounts = result.scalars().all()
    return templates.TemplateResponse("accounts/list.html", {"request": request, "accounts": accounts, "page_title": "Аккаунты"})


@router.get("/new", response_class=HTMLResponse)
async def account_new(request: Request):
    return templates.TemplateResponse("accounts/form.html", {"request": request, "account": None, "page_title": "Аккаунты"})


@router.post("/new")
async def account_create(
    request: Request,
    name: str = Form(...),
    client_id: str = Form(""),
    client_secret: str = Form(""),
    phone: str = Form(""),
    address: str = Form(""),
    report_email: str = Form(""),
    schedule: str = Form(""),
    autoload_enabled: str = Form(""),
    avito_sync_minute: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    sync_min = int(avito_sync_minute) if avito_sync_minute.strip() else None
    encrypted_secret = encrypt(client_secret) if client_secret else None
    account = Account(
        name=name,
        client_id=client_id or None,
        client_secret=encrypted_secret,
        phone=phone or None,
        address=address or None,
        report_email=report_email or None,
        schedule=schedule or None,
        autoload_enabled=autoload_enabled == "1",
        avito_sync_minute=sync_min,
    )
    db.add(account)
    await db.commit()
    return RedirectResponse(f"/accounts/{account.id}", status_code=303)


@router.get("/{account_id}", response_class=HTMLResponse)
async def account_detail(request: Request, account_id: int, db: AsyncSession = Depends(get_db)):
    account = await db.get(Account, account_id)
    if not account:
        return HTMLResponse("Аккаунт не найден", status_code=404)
    return templates.TemplateResponse("accounts/detail.html", {"page_title": "Аккаунты",
        "request": request, "account": account, "base_url": settings.BASE_URL,
    })


@router.get("/{account_id}/edit", response_class=HTMLResponse)
async def account_edit(request: Request, account_id: int, db: AsyncSession = Depends(get_db)):
    account = await db.get(Account, account_id)
    if not account:
        return HTMLResponse("Аккаунт не найден", status_code=404)
    # Decrypt client_secret for form display
    decrypted_secret = ""
    if account.client_secret:
        try:
            decrypted_secret = decrypt(account.client_secret)
        except Exception:
            decrypted_secret = ""
    return templates.TemplateResponse("accounts/form.html", {
        "request": request, "account": account,
        "decrypted_secret": decrypted_secret, "page_title": "Аккаунты",
    })


@router.post("/{account_id}/edit")
async def account_update(
    request: Request,
    account_id: int,
    name: str = Form(...),
    client_id: str = Form(""),
    client_secret: str = Form(""),
    phone: str = Form(""),
    address: str = Form(""),
    report_email: str = Form(""),
    schedule: str = Form(""),
    autoload_enabled: str = Form(""),
    avito_sync_minute: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    account = await db.get(Account, account_id)
    if not account:
        return HTMLResponse("Аккаунт не найден", status_code=404)
    account.name = name
    account.client_id = client_id or None
    account.client_secret = encrypt(client_secret) if client_secret else None
    account.phone = phone or None
    account.address = address or None
    account.report_email = report_email or None
    account.schedule = schedule or None
    account.autoload_enabled = autoload_enabled == "1"
    account.avito_sync_minute = int(avito_sync_minute) if avito_sync_minute.strip() else None
    await db.commit()
    return RedirectResponse(f"/accounts/{account.id}", status_code=303)


@router.get("/{account_id}/avito-profile")
async def get_avito_profile(account_id: int, db: AsyncSession = Depends(get_db)):
    """Read-only diagnostic: fetch raw Avito autoload profile for an account."""
    account = await db.get(Account, account_id)
    if not account:
        return JSONResponse({"ok": False, "error": "Аккаунт не найден"}, status_code=404)
    if not account.client_id or not account.client_secret:
        return JSONResponse(
            {"ok": False, "error": f"Не заполнены credentials для аккаунта {account.name}"},
            status_code=400,
        )
    client = AvitoClient(account, db)
    try:
        profile = await client.get_profile()
        return JSONResponse({"ok": True, "profile": profile})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=502)
    finally:
        await client.close()


@router.get("/{account_id}/description-template")
async def get_description_template(account_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AccountDescriptionTemplate).where(AccountDescriptionTemplate.account_id == account_id)
    )
    tpl = result.scalar_one_or_none()
    return JSONResponse({"description_template": tpl.description_template if tpl else ""})


@router.patch("/{account_id}/description-template")
async def update_description_template(account_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    body = await request.json()
    text = body.get("description_template", "")

    result = await db.execute(
        select(AccountDescriptionTemplate).where(AccountDescriptionTemplate.account_id == account_id)
    )
    tpl = result.scalar_one_or_none()
    if tpl:
        tpl.description_template = text
    else:
        tpl = AccountDescriptionTemplate(account_id=account_id, description_template=text)
        db.add(tpl)
    await db.commit()
    return JSONResponse({"ok": True})


_MAX_EXCEL_BYTES = 20 * 1024 * 1024  # 20 MB


@router.post("/{account_id}/import-excel")
async def import_excel_endpoint(
    account_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload an Avito Excel export — match products by avito_id/title and
    backfill brand/goods_type/photos."""
    account = await db.get(Account, account_id)
    if not account:
        return JSONResponse({"ok": False, "error": "Аккаунт не найден"}, status_code=404)

    fname = (file.filename or "").lower()
    if not fname.endswith(".xlsx"):
        return JSONResponse(
            {"ok": False, "error": "Принимаются только .xlsx файлы"},
            status_code=400,
        )

    content = await file.read()
    if len(content) == 0:
        return JSONResponse({"ok": False, "error": "Пустой файл"}, status_code=400)
    if len(content) > _MAX_EXCEL_BYTES:
        return JSONResponse(
            {"ok": False, "error": f"Файл слишком большой: {len(content)} > {_MAX_EXCEL_BYTES} байт"},
            status_code=413,
        )

    try:
        counters = await import_avito_excel(account_id, content, db)
    except InvalidExcelError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    return JSONResponse({"ok": True, **counters})
