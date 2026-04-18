"""Routes for standalone description templates (decoupled from accounts)."""

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.description_template import DescriptionTemplate

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["description_templates"])
templates = Jinja2Templates(directory="app/templates")

_NAME_MAX = 100
_BODY_MAX = 5000


# ── Settings redirect ──

@router.get("/settings", response_class=RedirectResponse)
async def settings_redirect():
    return RedirectResponse("/settings/description-templates", status_code=302)


# ── HTML page ──

@router.get("/settings/description-templates", response_class=HTMLResponse)
async def templates_page(request: Request):
    return templates.TemplateResponse(
        "settings/description_templates.html",
        {"request": request, "page_title": "Шаблоны описаний"},
    )


# ── JSON API ──

@router.get("/api/description-templates")
async def list_templates(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(DescriptionTemplate).order_by(DescriptionTemplate.updated_at.desc())
    )
    rows = result.scalars().all()
    return {
        "ok": True,
        "templates": [
            {
                "id": t.id,
                "name": t.name,
                "body": t.body,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "updated_at": t.updated_at.isoformat() if t.updated_at else None,
            }
            for t in rows
        ],
    }


@router.post("/api/description-templates", status_code=201)
async def create_template(request: Request, db: AsyncSession = Depends(get_db)):
    data = await request.json()
    name = (data.get("name") or "").strip()
    body = (data.get("body") or "").strip()

    if not name or len(name) > _NAME_MAX:
        return JSONResponse(
            {"ok": False, "error": f"name must be 1–{_NAME_MAX} characters"},
            status_code=422,
        )
    if not body or len(body) > _BODY_MAX:
        return JSONResponse(
            {"ok": False, "error": f"body must be 1–{_BODY_MAX} characters"},
            status_code=422,
        )

    tpl = DescriptionTemplate(name=name, body=body)
    db.add(tpl)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return JSONResponse(
            {"ok": False, "error": f"Template with name '{name}' already exists"},
            status_code=409,
        )
    await db.refresh(tpl)
    logger.info("template_created", template_id=tpl.id, name=name)
    return JSONResponse({"ok": True, "id": tpl.id}, status_code=201)


@router.patch("/api/description-templates/{template_id}")
async def update_template(template_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    tpl = await db.get(DescriptionTemplate, template_id)
    if not tpl:
        return JSONResponse({"ok": False, "error": "Not found"}, status_code=404)

    data = await request.json()

    if "name" in data:
        name = (data["name"] or "").strip()
        if not name or len(name) > _NAME_MAX:
            return JSONResponse(
                {"ok": False, "error": f"name must be 1–{_NAME_MAX} characters"},
                status_code=422,
            )
        tpl.name = name

    if "body" in data:
        body = (data["body"] or "").strip()
        if not body or len(body) > _BODY_MAX:
            return JSONResponse(
                {"ok": False, "error": f"body must be 1–{_BODY_MAX} characters"},
                status_code=422,
            )
        tpl.body = body

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return JSONResponse(
            {"ok": False, "error": "Template with this name already exists"},
            status_code=409,
        )
    logger.info("template_updated", template_id=template_id)
    return {"ok": True}


@router.delete("/api/description-templates/{template_id}", status_code=204)
async def delete_template(template_id: int, db: AsyncSession = Depends(get_db)):
    tpl = await db.get(DescriptionTemplate, template_id)
    if not tpl:
        return JSONResponse({"ok": False, "error": "Not found"}, status_code=404)
    await db.delete(tpl)
    await db.commit()
    logger.info("template_deleted", template_id=template_id)
