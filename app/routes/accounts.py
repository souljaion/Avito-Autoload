from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.models.account import Account

router = APIRouter(prefix="/accounts", tags=["accounts"])
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
async def account_list(request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Account).order_by(Account.id.desc()))
    accounts = result.scalars().all()
    return templates.TemplateResponse("accounts/list.html", {"request": request, "accounts": accounts})


@router.get("/new", response_class=HTMLResponse)
async def account_new(request: Request):
    return templates.TemplateResponse("accounts/form.html", {"request": request, "account": None})


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
    db: AsyncSession = Depends(get_db),
):
    account = Account(
        name=name,
        client_id=client_id or None,
        client_secret=client_secret or None,
        phone=phone or None,
        address=address or None,
        report_email=report_email or None,
        schedule=schedule or None,
        autoload_enabled=autoload_enabled == "1",
    )
    db.add(account)
    await db.commit()
    return RedirectResponse(f"/accounts/{account.id}", status_code=303)


@router.get("/{account_id}", response_class=HTMLResponse)
async def account_detail(request: Request, account_id: int, db: AsyncSession = Depends(get_db)):
    account = await db.get(Account, account_id)
    if not account:
        return HTMLResponse("Аккаунт не найден", status_code=404)
    return templates.TemplateResponse("accounts/detail.html", {
        "request": request, "account": account, "base_url": settings.BASE_URL,
    })


@router.get("/{account_id}/edit", response_class=HTMLResponse)
async def account_edit(request: Request, account_id: int, db: AsyncSession = Depends(get_db)):
    account = await db.get(Account, account_id)
    if not account:
        return HTMLResponse("Аккаунт не найден", status_code=404)
    return templates.TemplateResponse("accounts/form.html", {"request": request, "account": account})


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
    db: AsyncSession = Depends(get_db),
):
    account = await db.get(Account, account_id)
    if not account:
        return HTMLResponse("Аккаунт не найден", status_code=404)
    account.name = name
    account.client_id = client_id or None
    account.client_secret = client_secret or None
    account.phone = phone or None
    account.address = address or None
    account.report_email = report_email or None
    account.schedule = schedule or None
    account.autoload_enabled = autoload_enabled == "1"
    await db.commit()
    return RedirectResponse(f"/accounts/{account.id}", status_code=303)
