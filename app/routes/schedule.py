from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.models.product import Product

router = APIRouter(tags=["schedule"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/schedule", response_class=HTMLResponse)
async def schedule_page(request: Request):
    return templates.TemplateResponse("schedule.html", {"request": request})


@router.get("/api/schedule")
async def schedule_data(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Product)
        .options(selectinload(Product.account), selectinload(Product.images))
        .where(Product.status.in_(["scheduled", "published"]))
        .order_by(Product.scheduled_at.asc())
    )
    products = result.scalars().all()

    items = []
    for p in products:
        first_image = None
        if p.images:
            sorted_imgs = sorted(p.images, key=lambda x: (not x.is_main, x.sort_order))
            first_image = sorted_imgs[0].url

        items.append({
            "id": p.id,
            "title": p.title,
            "status": p.status,
            "price": p.price,
            "account": p.account.name if p.account else None,
            "image": first_image,
            "scheduled_at": p.scheduled_at.strftime("%d.%m.%Y %H:%M") if p.scheduled_at else None,
            "scheduled_at_iso": p.scheduled_at.isoformat() if p.scheduled_at else None,
            "published_at": p.published_at.strftime("%d.%m.%Y %H:%M") if p.published_at else None,
        })

    return JSONResponse({"items": items})


@router.post("/api/schedule/{product_id}/cancel")
async def cancel_scheduled(product_id: int, db: AsyncSession = Depends(get_db)):
    product = await db.get(Product, product_id)
    if not product:
        return JSONResponse({"ok": False, "error": "Товар не найден"}, status_code=404)
    if product.status != "scheduled":
        return JSONResponse({"ok": False, "error": "Товар не в статусе scheduled"}, status_code=400)

    product.status = "draft"
    product.scheduled_at = None
    product.scheduled_account_id = None
    await db.commit()
    return JSONResponse({"ok": True})
