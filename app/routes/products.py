import os
import shutil
from datetime import datetime as dt, timezone
from zoneinfo import ZoneInfo

import aiofiles
import structlog
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db import get_db
from app.models.account import Account
from app.models.listing import Listing
from app.models.product import Product
from app.models.product_image import ProductImage
from app.models.model import Model
from app.models.photo_pack_image import PhotoPackImage
from app.rate_limit import limiter
from app.services.feed_generator import is_ready_for_feed, get_missing_fields

MSK = ZoneInfo("Europe/Moscow")


def _to_utc_naive(val: dt) -> dt:
    """Convert a datetime to naive UTC. Treat naive datetimes as Moscow time."""
    if val.tzinfo is None:
        val = val.replace(tzinfo=MSK)
    return val.astimezone(timezone.utc).replace(tzinfo=None)


def _get_feed_problems(product: Product, has_account_template: bool = False) -> list[str]:
    """Return list of human-readable problems preventing feed readiness.

    Delegates to get_missing_fields() — single source of truth.
    """
    return get_missing_fields(product, has_account_template)
from app.schemas.product import ProductCreateForm
from app.services.avito_client import AvitoClient
from app.services.photo_uniquifier import uniquify_image_async

logger = structlog.get_logger(__name__)
from app.catalog import (
    get_catalog, DEFAULT_CONDITION,
    AD_TYPES, DEFAULT_AD_TYPE,
    AVAILABILITIES, DEFAULT_AVAILABILITY,
    DELIVERY_OPTIONS, DEFAULT_DELIVERY,
    DELIVERY_SUBSIDIES, DEFAULT_DELIVERY_SUBSIDY,
    MULTI_ITEM_OPTIONS, DEFAULT_MULTI_ITEM,
    TRY_ON_OPTIONS, DEFAULT_TRY_ON,
)

router = APIRouter(prefix="/products", tags=["products"])
templates = Jinja2Templates(directory="app/templates")

PRODUCT_STATUSES = ["draft", "imported", "active", "paused", "sold", "scheduled", "published", "removed"]

EXTRA_FIELD_OPTIONS = {
    "ad_types": AD_TYPES,
    "availabilities": AVAILABILITIES,
    "delivery_options": DELIVERY_OPTIONS,
    "delivery_subsidies": DELIVERY_SUBSIDIES,
    "multi_item_options": MULTI_ITEM_OPTIONS,
    "try_on_options": TRY_ON_OPTIONS,
    "default_ad_type": DEFAULT_AD_TYPE,
    "default_availability": DEFAULT_AVAILABILITY,
    "default_delivery": DEFAULT_DELIVERY,
    "default_delivery_subsidy": DEFAULT_DELIVERY_SUBSIDY,
    "default_multi_item": DEFAULT_MULTI_ITEM,
    "default_try_on": DEFAULT_TRY_ON,
}


@router.get("/search")
async def search_products(q: str = "", account_id: int | None = None, db: AsyncSession = Depends(get_db)):
    """Search unlinked products by title for model linking."""
    q = q.strip()
    if len(q) < 2:
        return JSONResponse([])
    words = q.split()
    filters = [Product.model_id.is_(None)]
    for word in words:
        filters.append(Product.title.ilike(f"%{word}%"))
    if account_id:
        filters.append(Product.account_id == account_id)
    stmt = (
        select(Product)
        .options(selectinload(Product.account), selectinload(Product.images))
        .where(*filters)
        .order_by(Product.id.desc())
        .limit(20)
    )
    result = await db.execute(stmt)
    products = result.scalars().all()
    items = []
    for p in products:
        image_url = None
        if p.images:
            sorted_imgs = sorted(p.images, key=lambda x: (not x.is_main, x.sort_order))
            image_url = sorted_imgs[0].url
        elif p.image_url:
            image_url = p.image_url
        items.append({
            "id": p.id,
            "title": p.title,
            "account_name": p.account.name if p.account else None,
            "price": p.price,
            "status": p.status,
            "image_url": image_url,
        })
    return JSONResponse(items)


@router.get("", response_class=HTMLResponse)
async def product_list(request: Request, account_id: int | None = None, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(Product)
        .options(selectinload(Product.account), selectinload(Product.images))
        .order_by(Product.id.desc())
    )
    if account_id:
        stmt = stmt.where(Product.account_id == account_id)
    result = await db.execute(stmt)
    products = result.scalars().all()

    accs = await db.execute(select(Account).order_by(Account.name))
    accounts = accs.scalars().all()

    return templates.TemplateResponse("products/list.html", {
        "request": request, "products": products, "accounts": accounts,
        "selected_account_id": account_id,
    })


@router.post("/import-from-avito")
async def import_from_avito(request: Request, db: AsyncSession = Depends(get_db)):
    body = await request.json()
    account_id = body.get("account_id")
    if not account_id:
        return JSONResponse({"ok": False, "error": "Не указан account_id"}, status_code=400)

    account = await db.get(Account, int(account_id))
    if not account:
        return JSONResponse({"ok": False, "error": "Аккаунт не найден"}, status_code=404)

    client = AvitoClient(account, db)
    try:
        avito_items = await client.get_user_items(status="active")
    except Exception as e:
        logger.error("Import failed for account %d: %s", account_id, e)
        return JSONResponse({"ok": False, "error": f"Ошибка Avito API: {e}"}, status_code=502)
    finally:
        await client.close()

    # Get existing avito_ids to skip duplicates
    existing_result = await db.execute(
        select(Product.avito_id).where(Product.avito_id.isnot(None))
    )
    existing_ids = {row[0] for row in existing_result.all()}

    imported = []
    skipped = 0
    for item in avito_items:
        avito_id = item.get("id")
        if not avito_id:
            continue
        if avito_id in existing_ids:
            skipped += 1
            continue

        cat = item.get("category") or {}
        product = Product(
            avito_id=avito_id,
            title=item.get("title", ""),
            price=item.get("price"),
            category=cat.get("name"),
            status="imported",
            account_id=account.id,
        )
        db.add(product)
        await db.flush()
        db.add(Listing(product_id=product.id, account_id=account.id, status="draft"))
        existing_ids.add(avito_id)
        imported.append({
            "avito_id": avito_id,
            "title": item.get("title", ""),
            "price": item.get("price"),
            "url": item.get("url"),
        })

    await db.commit()

    return JSONResponse({
        "ok": True,
        "imported": len(imported),
        "skipped": skipped,
        "total": len(avito_items),
        "items": imported[:20],
    })


@router.get("/bulk-edit", response_class=HTMLResponse)
async def bulk_edit_page(request: Request, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(Product)
        .options(selectinload(Product.images))
        .where(Product.status.in_(["draft", "imported"]))
        .order_by(Product.id)
    )
    result = await db.execute(stmt)
    products = result.scalars().all()
    catalog = await get_catalog(db)
    return templates.TemplateResponse("products/bulk_edit.html", {
        "request": request, "products": products, **catalog,
    })


@router.post("/bulk-categories")
async def bulk_categories(request: Request, db: AsyncSession = Depends(get_db)):
    body = await request.json()
    product_ids = body.get("product_ids", [])
    if not product_ids:
        return JSONResponse({"ok": False, "error": "Не выбраны товары"}, status_code=400)

    category = body.get("category") or None
    goods_type = body.get("goods_type") or None
    subcategory = body.get("subcategory") or None
    goods_subtype = body.get("goods_subtype") or None

    result = await db.execute(
        select(Product).where(Product.id.in_(product_ids), Product.status.in_(["draft", "imported"]))
    )
    products = result.scalars().all()
    for p in products:
        if category:
            p.category = category
        if goods_type:
            p.goods_type = goods_type
        if subcategory:
            p.subcategory = subcategory
        if goods_subtype:
            p.goods_subtype = goods_subtype
    await db.commit()
    return JSONResponse({"ok": True, "updated": len(products)})


@router.post("/bulk-descriptions")
async def bulk_descriptions(request: Request, db: AsyncSession = Depends(get_db)):
    body = await request.json()
    product_ids = body.get("product_ids", [])
    if not product_ids:
        return JSONResponse({"ok": False, "error": "Не выбраны товары"}, status_code=400)

    result = await db.execute(
        select(Product).where(Product.id.in_(product_ids))
    )
    products = result.scalars().all()
    items = []
    for p in products:
        parts = []
        # Title is always present
        parts.append(p.title.strip())
        if p.brand:
            parts.append(f"Бренд: {p.brand}.")
        if p.size:
            parts.append(f"Размер: {p.size}.")
        if p.color:
            parts.append(f"Цвет: {p.color}.")
        if p.material:
            parts.append(f"Материал: {p.material}.")
        if p.condition:
            parts.append(f"Состояние: {p.condition}.")
        # Category context
        cat_parts = []
        if p.goods_type:
            cat_parts.append(p.goods_type)
        if p.subcategory:
            cat_parts.append(p.subcategory)
        if p.goods_subtype:
            cat_parts.append(p.goods_subtype)
        if cat_parts:
            parts.append("Категория: " + " / ".join(cat_parts) + ".")
        # Price info
        if p.price:
            parts.append(f"Цена: {p.price:,} руб.".replace(",", " "))

        desc = "\n".join(parts)
        p.description = desc
        items.append({"id": p.id, "description": desc})
    await db.commit()
    return JSONResponse({"ok": True, "updated": len(items), "items": items})


@router.post("/bulk-activate")
async def bulk_activate(request: Request, db: AsyncSession = Depends(get_db)):
    body = await request.json()
    product_ids = body.get("product_ids", [])
    if not product_ids:
        return JSONResponse({"ok": False, "error": "Не выбраны товары"}, status_code=400)

    result = await db.execute(
        select(Product).where(Product.id.in_(product_ids), Product.status.in_(["draft", "imported"]))
    )
    products = result.scalars().all()
    activated_ids = []
    skipped = 0
    for p in products:
        # Check required fields
        if p.goods_type and p.subcategory and p.description and p.price:
            p.status = "active"
            activated_ids.append(p.id)
        else:
            skipped += 1
    await db.commit()
    return JSONResponse({
        "ok": True,
        "activated": len(activated_ids),
        "skipped": skipped,
        "activated_ids": activated_ids,
    })


@router.get("/new", response_class=HTMLResponse)
async def product_new(request: Request, model_id: int | None = None, db: AsyncSession = Depends(get_db)):
    accs = await db.execute(select(Account).order_by(Account.name))
    models = await db.execute(select(Model).order_by(Model.name))
    catalog = await get_catalog(db)
    return templates.TemplateResponse("products/form.html", {
        "request": request, "product": None, "accounts": accs.scalars().all(),
        "models": models.scalars().all(),
        "preselect_model_id": model_id,
        "statuses": PRODUCT_STATUSES,
        **catalog, **EXTRA_FIELD_OPTIONS,
    })


@router.post("/new")
async def product_create(
    request: Request,
    title: str = Form(...),
    sku: str = Form(""),
    brand: str = Form(""),
    model: str = Form(""),
    category: str = Form(""),
    goods_type: str = Form(""),
    subcategory: str = Form(""),
    goods_subtype: str = Form(""),
    size: str = Form(""),
    color: str = Form(""),
    material: str = Form(""),
    condition: str = Form(""),
    price: str = Form("0"),
    description: str = Form(""),
    status: str = Form("draft"),
    account_id: str = Form(""),
    ad_type: str = Form(""),
    availability: str = Form(""),
    delivery: str = Form(""),
    delivery_subsidy: str = Form(""),
    multi_item: str = Form(""),
    try_on: str = Form(""),
    model_id: str = Form(""),
    pack_id: str = Form(""),
    pack_uniquify: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    # Validate with Pydantic
    from pydantic import ValidationError
    try:
        form = ProductCreateForm(
            title=title, sku=sku, brand=brand, model=model,
            category=category, goods_type=goods_type, subcategory=subcategory,
            goods_subtype=goods_subtype, size=size, color=color, material=material,
            condition=condition, price=price, description=description, status=status,
            account_id=account_id, ad_type=ad_type, availability=availability,
            delivery=delivery, delivery_subsidy=delivery_subsidy, multi_item=multi_item,
            try_on=try_on, model_id=model_id, pack_id=pack_id, pack_uniquify=pack_uniquify,
        )
    except ValidationError as e:
        errors = "; ".join(f"{err['loc'][-1]}: {err['msg']}" for err in e.errors())
        return JSONResponse({"ok": False, "error": errors}, status_code=400)

    price_int = form.validated_price()

    acct_id = int(account_id) if account_id else None
    if acct_id:
        acct = await db.get(Account, acct_id)
        if not acct:
            return JSONResponse({"ok": False, "error": f"Account {acct_id} not found"}, status_code=400)

    product = Product(
        title=form.title,
        sku=sku or None,
        brand=brand or None,
        model=model or None,
        model_id=int(model_id) if model_id else None,
        category=category or None,
        goods_type=goods_type or None,
        subcategory=subcategory or None,
        goods_subtype=goods_subtype or None,
        size=size or None,
        color=color or None,
        material=material or None,
        condition=condition or DEFAULT_CONDITION,
        price=price_int,
        description=description or None,
        status=status,
        account_id=acct_id,
        extra={
            "ad_type": ad_type or DEFAULT_AD_TYPE,
            "availability": availability or DEFAULT_AVAILABILITY,
            "delivery": delivery or DEFAULT_DELIVERY,
            "delivery_subsidy": delivery_subsidy or DEFAULT_DELIVERY_SUBSIDY,
            "multi_item": multi_item or DEFAULT_MULTI_ITEM,
            "try_on": try_on or DEFAULT_TRY_ON,
        },
    )
    db.add(product)
    await db.flush()

    # Apply photo pack if selected
    if pack_id:
        await _apply_pack_to_product(db, product.id, int(pack_id), pack_uniquify == "1")

    # Auto-create listing so product is visible on /products page
    if product.account_id:
        db.add(Listing(product_id=product.id, account_id=product.account_id, status="draft"))

    await db.commit()
    return RedirectResponse(f"/products/{product.id}", status_code=303)


@router.get("/{product_id}", response_class=HTMLResponse)
async def product_detail(request: Request, product_id: int, db: AsyncSession = Depends(get_db)):
    stmt = select(Product).options(
        selectinload(Product.account), selectinload(Product.images)
    ).where(Product.id == product_id)
    result = await db.execute(stmt)
    product = result.scalar_one_or_none()
    if not product:
        return HTMLResponse("Товар не найден", status_code=404)
    return templates.TemplateResponse("products/detail.html", {"request": request, "product": product, "page_title": "Объявления"})


@router.get("/{product_id}/avito-status")
@limiter.limit("30/minute")
async def product_avito_status(
    request: Request,
    product_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Fetch real-time Avito autoload status for a single product."""
    result = await db.execute(
        select(Product).options(selectinload(Product.account)).where(Product.id == product_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        return JSONResponse({"ok": False, "error": "Товар не найден"}, status_code=404)
    if not product.account or not product.account.client_id:
        return JSONResponse({"ok": False, "error": "Аккаунт не настроен"}, status_code=400)

    client = AvitoClient(product.account, db)
    try:
        items = await client.get_items_info([str(product.id)])
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Ошибка Avito API: {e}"}, status_code=502)
    finally:
        await client.close()

    if not items:
        return JSONResponse({"ok": False, "error": "Объявление не найдено в Avito"}, status_code=404)

    item = items[0]
    return JSONResponse({
        "ok": True,
        "avito_status": item.get("avito_status"),
        "url": item.get("url"),
        "messages": item.get("messages"),
        "processing_time": item.get("processing_time"),
        "avito_date_end": item.get("avito_date_end"),
    })


@router.get("/{product_id}/edit", response_class=HTMLResponse)
async def product_edit(request: Request, product_id: int, inline: int = 0, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Product)
        .options(selectinload(Product.images), selectinload(Product.description_template))
        .where(Product.id == product_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        return HTMLResponse("Товар не найден", status_code=404)
    accs = await db.execute(select(Account).order_by(Account.name))
    models = await db.execute(select(Model).order_by(Model.name))
    catalog = await get_catalog(db)

    # Load Yandex.Disk folders
    from app.models.product_yandex_folder import ProductYandexFolder
    yf_result = await db.execute(
        select(ProductYandexFolder)
        .where(ProductYandexFolder.product_id == product_id)
        .order_by(ProductYandexFolder.id)
    )
    yandex_folders = yf_result.scalars().all()

    template_name = "products/form_inline.html" if inline else "products/form.html"
    return templates.TemplateResponse(template_name, {
        "request": request, "product": product, "accounts": accs.scalars().all(),
        "models": models.scalars().all(),
        "statuses": PRODUCT_STATUSES,
        "yandex_folders": yandex_folders,
        "inline": bool(inline),
        **catalog, **EXTRA_FIELD_OPTIONS,
    })


@router.post("/{product_id}/edit")
async def product_update(
    request: Request,
    product_id: int,
    title: str = Form(...),
    sku: str = Form(""),
    brand: str = Form(""),
    model: str = Form(""),
    category: str = Form(""),
    goods_type: str = Form(""),
    subcategory: str = Form(""),
    goods_subtype: str = Form(""),
    size: str = Form(""),
    color: str = Form(""),
    material: str = Form(""),
    condition: str = Form(""),
    price: str = Form("0"),
    description: str = Form(""),
    status: str = Form("draft"),
    account_id: str = Form(""),
    ad_type: str = Form(""),
    availability: str = Form(""),
    delivery: str = Form(""),
    delivery_subsidy: str = Form(""),
    multi_item: str = Form(""),
    try_on: str = Form(""),
    schedule_enabled: str = Form(""),
    scheduled_at: str = Form(""),
    scheduled_account_id: str = Form(""),
    model_id: str = Form(""),
    inline: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    product = await db.get(Product, product_id)
    if not product:
        return HTMLResponse("Товар не найден", status_code=404)
    product.title = title
    product.sku = sku or None
    product.brand = brand or None
    product.model = model or None
    product.category = category or None
    product.goods_type = goods_type or None
    product.subcategory = subcategory or None
    product.goods_subtype = goods_subtype or None
    product.size = size or None
    product.color = color or None
    product.material = material or None
    product.condition = condition or DEFAULT_CONDITION
    try:
        product.price = int(price) if price and price.strip() else None
    except (ValueError, TypeError):
        product.price = None
    product.description = description or None
    product.account_id = int(account_id) if account_id else None
    product.model_id = int(model_id) if model_id else None
    product.extra = {
        "ad_type": ad_type or DEFAULT_AD_TYPE,
        "availability": availability or DEFAULT_AVAILABILITY,
        "delivery": delivery or DEFAULT_DELIVERY,
        "delivery_subsidy": delivery_subsidy or DEFAULT_DELIVERY_SUBSIDY,
        "multi_item": multi_item or DEFAULT_MULTI_ITEM,
        "try_on": try_on or DEFAULT_TRY_ON,
    }

    if schedule_enabled == "1" and scheduled_at:
        from datetime import datetime as dt
        try:
            product.scheduled_at = dt.fromisoformat(scheduled_at)
        except ValueError:
            product.scheduled_at = None
        product.scheduled_account_id = int(scheduled_account_id) if scheduled_account_id else product.account_id
        product.status = "scheduled"
    else:
        if product.status == "scheduled":
            product.status = status if status != "scheduled" else "draft"
        else:
            product.status = status
        product.scheduled_at = None
        product.scheduled_account_id = None

    await db.commit()

    if inline == "1":
        return HTMLResponse(
            f'<html><body><script>'
            f'window.parent.postMessage({{type:"product-saved",productId:{product.id}}},window.location.origin);'
            f'</script><p style="text-align:center;padding:40px;font-family:sans-serif;color:#166534;">'
            f'Сохранено</p></body></html>'
        )

    return RedirectResponse(f"/products/{product.id}", status_code=303)


@router.post("/{product_id}/duplicate")
async def duplicate_product(product_id: int, db: AsyncSession = Depends(get_db)):
    product = await db.get(Product, product_id)
    if not product:
        return HTMLResponse("Товар не найден", status_code=404)

    copy = Product(
        title=product.title + " (копия)",
        sku=None,
        brand=product.brand,
        model=product.model,
        category=product.category,
        goods_type=product.goods_type,
        subcategory=product.subcategory,
        goods_subtype=product.goods_subtype,
        size=product.size,
        color=product.color,
        material=product.material,
        condition=product.condition,
        price=product.price,
        description=product.description,
        use_custom_description=product.use_custom_description,
        description_template_id=product.description_template_id,
        status="draft",
        account_id=product.account_id,
        model_id=product.model_id,
        extra=dict(product.extra) if product.extra else None,
    )
    db.add(copy)
    await db.flush()

    if copy.account_id:
        db.add(Listing(product_id=copy.id, account_id=copy.account_id, status="draft"))

    await db.commit()
    return RedirectResponse(f"/products/{copy.id}/edit", status_code=303)


@router.patch("/{product_id}")
async def patch_product(product_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    product = await db.get(Product, product_id)
    if not product:
        return JSONResponse({"ok": False, "error": "Товар не найден"}, status_code=404)

    body = await request.json()

    if "price" in body:
        val = body["price"]
        try:
            product.price = int(val) if val is not None and str(val).strip() else None
        except (ValueError, TypeError):
            return JSONResponse({"ok": False, "error": "Некорректная цена"}, status_code=400)

    if "status" in body:
        val = body["status"]
        if val not in PRODUCT_STATUSES:
            return JSONResponse({"ok": False, "error": f"Недопустимый статус: {val}"}, status_code=400)
        old_status = product.status
        product.status = val
        # If cancelling a scheduled product, clear scheduled_at and sync listings
        if old_status == "scheduled" and val == "draft":
            product.scheduled_at = None
            listings_result = await db.execute(
                select(Listing).where(
                    Listing.product_id == product_id,
                    Listing.status == "scheduled",
                )
            )
            for listing in listings_result.scalars().all():
                listing.status = "draft"
                listing.scheduled_at = None

    if "title" in body:
        product.title = body["title"].strip() if body["title"] else product.title

    if "description" in body:
        product.description = body["description"].strip() or None

    if "use_custom_description" in body:
        product.use_custom_description = bool(body["use_custom_description"])

    if "size" in body:
        product.size = body["size"].strip() or None

    if "condition" in body:
        product.condition = body["condition"].strip() or None

    if "brand" in body:
        v = body["brand"]
        product.brand = v.strip()[:255] if isinstance(v, str) and v.strip() else None

    if "goods_type" in body:
        v = body["goods_type"]
        product.goods_type = v.strip()[:255] if isinstance(v, str) and v.strip() else None

    if "model_id" in body:
        val = body["model_id"]
        product.model_id = int(val) if val is not None else None

    if "description_template_id" in body:
        val = body["description_template_id"]
        if val is not None:
            from app.models.description_template import DescriptionTemplate
            tpl = await db.get(DescriptionTemplate, int(val))
            if not tpl:
                return JSONResponse(
                    {"ok": False, "error": f"Шаблон с id={val} не найден"},
                    status_code=404,
                )
            product.description_template_id = tpl.id
        else:
            product.description_template_id = None

    if "account_id" in body:
        val = body["account_id"]
        product.account_id = int(val) if val else None

    await db.commit()
    return JSONResponse({"ok": True, "id": product.id, "price": product.price, "status": product.status})


@router.delete("/{product_id}")
async def delete_product(product_id: int, db: AsyncSession = Depends(get_db)):
    product = await db.get(Product, product_id)
    if not product:
        return JSONResponse({"ok": False, "error": "Товар не найден"}, status_code=404)

    product.status = "removed"
    product.removed_at = dt.utcnow()

    # Update related listings
    listing_result = await db.execute(
        select(Listing).where(Listing.product_id == product_id)
    )
    for ls in listing_result.scalars().all():
        ls.status = "draft"

    await db.commit()

    # Diagnostic: which account's feed will carry the Status=Removed entry.
    # If avito_id is NULL the item won't be in any feed (nothing for Avito to remove);
    # if account_id is NULL the item is orphaned and also won't be in any feed.
    feed_account_id = product.account_id if product.avito_id else None
    if not feed_account_id and product.avito_id:
        logger.warning(
            "delete_product.no_feed_account",
            product_id=product.id,
            avito_id=product.avito_id,
            reason="avito_id present but account_id is NULL — feed will not include this product",
        )

    return JSONResponse({
        "ok": True,
        "status": "removed",
        "avito_id": product.avito_id,
        "account_id": product.account_id,
        "feed_account_id": feed_account_id,
        "in_feed": feed_account_id is not None,
    })


async def _apply_pack_to_product(db: AsyncSession, product_id: int, pack_id: int, do_uniquify: bool) -> int:
    """Copy photos from a pack to a product. Returns count of images added."""
    result = await db.execute(
        select(PhotoPackImage)
        .where(PhotoPackImage.pack_id == pack_id)
        .order_by(PhotoPackImage.sort_order)
    )
    pack_images = result.scalars().all()
    if not pack_images:
        return 0

    product_dir = os.path.join(settings.MEDIA_DIR, "products", str(product_id))
    os.makedirs(product_dir, exist_ok=True)

    # Find current max sort_order
    existing = await db.execute(
        select(ProductImage)
        .where(ProductImage.product_id == product_id)
        .order_by(ProductImage.sort_order.desc())
    )
    existing_imgs = existing.scalars().all()
    max_order = existing_imgs[0].sort_order if existing_imgs else -1
    has_main = any(img.is_main for img in existing_imgs)

    count = 0
    for i, pimg in enumerate(pack_images):
        if not os.path.isfile(pimg.file_path):
            continue

        order = max_order + 1 + i
        basename = os.path.basename(pimg.file_path)
        filename = f"{order}_{basename}"
        filepath = os.path.join(product_dir, filename)

        if do_uniquify:
            data = await uniquify_image_async(pimg.file_path)
            async with aiofiles.open(filepath, "wb") as f:
                await f.write(data)
        else:
            shutil.copy2(pimg.file_path, filepath)

        url = f"/media/products/{product_id}/{filename}"
        is_main = not has_main and i == 0

        img_record = ProductImage(
            product_id=product_id,
            url=url,
            filename=filename,
            sort_order=order,
            is_main=is_main,
        )
        db.add(img_record)
        if is_main:
            has_main = True
        count += 1

    return count


@router.post("/{product_id}/apply-pack")
async def apply_pack(product_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    product = await db.get(Product, product_id)
    if not product:
        return JSONResponse({"ok": False, "error": "Товар не найден"}, status_code=404)

    body = await request.json()
    pack_id = body.get("pack_id")
    do_uniquify = body.get("uniquify", False)

    if not pack_id:
        return JSONResponse({"ok": False, "error": "Не указан pack_id"}, status_code=400)

    count = await _apply_pack_to_product(db, product_id, int(pack_id), do_uniquify)
    await db.commit()
    return JSONResponse({"ok": True, "images_added": count})


@router.patch("/{product_id}/pack")
async def patch_product_pack(product_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    """Change the photo pack assigned to a product."""
    from app.models.pack_usage_history import PackUsageHistory

    product = await db.get(Product, product_id)
    if not product:
        return JSONResponse({"ok": False, "error": "Товар не найден"}, status_code=404)

    body = await request.json()
    pack_id = body.get("pack_id")
    if not pack_id:
        return JSONResponse({"ok": False, "error": "Не указан pack_id"}, status_code=400)

    count = await _apply_pack_to_product(db, product_id, int(pack_id), False)

    # Update pack usage history so accounts-status reflects the current pack
    if product.account_id and product.model_id:
        from app.models.photo_pack import PhotoPack
        # Get all pack IDs for this model
        model_packs = await db.execute(
            select(PhotoPack.id).where(PhotoPack.model_id == product.model_id)
        )
        model_pack_ids = [r[0] for r in model_packs.all()]
        if model_pack_ids:
            # Remove old usage records for this account + this model's packs
            old_usage = await db.execute(
                select(PackUsageHistory).where(
                    PackUsageHistory.account_id == product.account_id,
                    PackUsageHistory.pack_id.in_(model_pack_ids),
                )
            )
            for old in old_usage.scalars().all():
                await db.delete(old)
        # Record new usage
        db.add(PackUsageHistory(
            pack_id=int(pack_id),
            account_id=product.account_id,
            uniquified=False,
        ))

    await db.commit()
    return JSONResponse({"ok": True, "images_added": count})


@router.post("/{product_id}/schedule")
async def schedule_product(product_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    body = await request.json()
    account_id = body.get("account_id")
    scheduled_at_str = body.get("scheduled_at")

    if not account_id or not scheduled_at_str:
        return JSONResponse({"ok": False, "error": "account_id and scheduled_at required"}, status_code=400)

    result = await db.execute(
        select(Product).options(selectinload(Product.images)).where(Product.id == product_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        return JSONResponse({"ok": False, "error": "Товар не найден"}, status_code=404)

    # Check if account has a description template
    from app.models.account_description_template import AccountDescriptionTemplate as ADT
    tmpl_result = await db.execute(select(ADT).where(ADT.account_id == int(account_id)))
    has_template = tmpl_result.scalar_one_or_none() is not None

    # Validate product readiness before scheduling
    problems = _get_feed_problems(product, has_account_template=has_template)
    if problems:
        return JSONResponse({
            "ok": False,
            "error": "Товар не готов к публикации",
            "problems": problems,
        }, status_code=400)

    try:
        scheduled_at = _to_utc_naive(dt.fromisoformat(scheduled_at_str))
    except ValueError:
        return JSONResponse({"ok": False, "error": "Invalid datetime"}, status_code=400)

    # Update product status and scheduled_at so /schedule page sees it
    product.status = "scheduled"
    product.scheduled_at = scheduled_at

    # Find or create listing
    result = await db.execute(
        select(Listing).where(Listing.product_id == product_id, Listing.account_id == int(account_id))
    )
    listing = result.scalar_one_or_none()
    if listing:
        listing.status = "scheduled"
        listing.scheduled_at = scheduled_at
    else:
        listing = Listing(
            product_id=product_id,
            account_id=int(account_id),
            status="scheduled",
            scheduled_at=scheduled_at,
        )
        db.add(listing)

    await db.commit()
    # Return display time in Moscow
    display_time = scheduled_at.replace(tzinfo=timezone.utc).astimezone(MSK)

    # Include sync hint if account has avito_sync_minute
    account = await db.get(Account, int(account_id))
    sync_hint = None
    if account and account.avito_sync_minute is not None:
        sync_min = account.avito_sync_minute
        sync_hint = f"Авито заберёт фид в XX:{sync_min:02d}, объявление появится не раньше этого времени"

    return JSONResponse({
        "ok": True,
        "scheduled_at": display_time.strftime("%d.%m.%Y %H:%M"),
        "sync_hint": sync_hint,
    })


@router.delete("/{product_id}/avito")
async def delete_from_avito(product_id: int, db: AsyncSession = Depends(get_db)):
    """Mark product as removed. Avito will deactivate the ad on next feed upload."""
    result = await db.execute(
        select(Product).options(selectinload(Product.account)).where(Product.id == product_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        return JSONResponse({"ok": False, "error": "Товар не найден"}, status_code=404)

    product.status = "removed"
    product.removed_at = dt.utcnow()

    # Also update related listings
    listing_result = await db.execute(
        select(Listing).where(Listing.product_id == product_id)
    )
    for ls in listing_result.scalars().all():
        if ls.status in ("published", "active"):
            ls.status = "draft"
            ls.avito_id = None

    await db.commit()
    msg = "Удалено. Авито снимет при следующей выгрузке фида (~1 час)" if product.avito_id else "Удалено из программы"
    return JSONResponse({"ok": True, "message": msg})


@router.post("/{product_id}/repost")
async def repost_product(product_id: int, db: AsyncSession = Depends(get_db)):
    """Hide old ad, re-apply pack with uniquification, generate & upload new feed."""
    import os
    import shutil
    import aiofiles
    from app.services.avito_client import AvitoClient
    from app.services.photo_uniquifier import uniquify_image_async
    from app.services.feed_generator import generate_feed
    from app.models.pack_usage_history import PackUsageHistory
    from app.models.photo_pack import PhotoPack
    from app.models.photo_pack_image import PhotoPackImage

    result = await db.execute(
        select(Product)
        .options(selectinload(Product.account), selectinload(Product.images))
        .where(Product.id == product_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        return JSONResponse({"ok": False, "error": "Товар не найден"}, status_code=404)
    if not product.account:
        return JSONResponse({"ok": False, "error": "Товар не привязан к аккаунту"}, status_code=400)

    account = product.account

    # 1. Old ad will be deactivated by Avito when new feed is uploaded (no direct API exists)

    # 2. Find last used pack for this account
    usage_result = await db.execute(
        select(PackUsageHistory)
        .where(PackUsageHistory.account_id == account.id)
        .order_by(PackUsageHistory.used_at.desc())
        .limit(1)
    )
    last_usage = usage_result.scalar_one_or_none()

    pack = None
    if last_usage:
        pack_result = await db.execute(
            select(PhotoPack)
            .options(selectinload(PhotoPack.images))
            .where(PhotoPack.id == last_usage.pack_id)
        )
        pack = pack_result.scalar_one_or_none()

    # 3. Re-apply pack with uniquification if pack found
    if pack and pack.images:
        # Delete old product images
        for img in list(product.images):
            await db.delete(img)

        product_dir = os.path.join(settings.MEDIA_DIR, "products", str(product.id))
        if os.path.isdir(product_dir):
            shutil.rmtree(product_dir)
        os.makedirs(product_dir, exist_ok=True)

        for idx, pimg in enumerate(sorted(pack.images, key=lambda x: x.sort_order)):
            if not os.path.isfile(pimg.file_path):
                continue
            basename = os.path.basename(pimg.file_path)
            filename = f"{idx}_{basename}"
            filepath = os.path.join(product_dir, filename)

            data = await uniquify_image_async(pimg.file_path)
            async with aiofiles.open(filepath, "wb") as f:
                await f.write(data)

            url = f"/media/products/{product.id}/{filename}"
            db.add(ProductImage(
                product_id=product.id,
                url=url,
                filename=filename,
                sort_order=idx,
                is_main=(idx == 0),
            ))

        db.add(PackUsageHistory(pack_id=pack.id, account_id=account.id, uniquified=True))

    # 4. Update status
    product.status = "active"
    product.avito_id = None
    await db.commit()

    # 5. Generate and upload feed
    try:
        filepath, count = await generate_feed(account.id, db)
        from app.models.feed_export import FeedExport
        feed_result = await db.execute(
            select(FeedExport)
            .where(FeedExport.account_id == account.id)
            .order_by(FeedExport.created_at.desc())
            .limit(1)
        )
        export = feed_result.scalar_one_or_none()
        if export:
            async with aiofiles.open(export.file_path, "rb") as f:
                xml_bytes = await f.read()
            client = AvitoClient(account, db)
            try:
                await client.upload_feed(xml_bytes, os.path.basename(export.file_path))
                from app.db import utc_now
                export.status = "uploaded"
                export.uploaded_at = utc_now()
                await db.commit()
            finally:
                await client.close()
    except Exception as e:
        return JSONResponse({"ok": True, "message": f"Фото обновлены, но загрузка фида не удалась: {e}"})

    return JSONResponse({"ok": True, "message": "Перевыложено успешно"})


@router.delete("/{product_id}/schedule")
async def cancel_schedule(product_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Listing).where(Listing.product_id == product_id, Listing.status == "scheduled")
    )
    listings = result.scalars().all()
    for ls in listings:
        ls.status = "draft"
        ls.scheduled_at = None
    await db.commit()
    return JSONResponse({"ok": True})


@router.post("/schedule-bulk")
async def schedule_bulk(request: Request, db: AsyncSession = Depends(get_db)):
    body = await request.json()
    product_ids = body.get("product_ids", [])
    account_id = body.get("account_id")
    start_time_str = body.get("start_time")
    interval_minutes = body.get("interval_minutes", 60)

    if not product_ids or not account_id or not start_time_str:
        return JSONResponse({"ok": False, "error": "Missing required fields"}, status_code=400)

    from datetime import timedelta
    try:
        start_time = _to_utc_naive(dt.fromisoformat(start_time_str))
    except ValueError:
        return JSONResponse({"ok": False, "error": "Invalid datetime"}, status_code=400)

    # Validate all products before scheduling any
    result = await db.execute(
        select(Product).options(selectinload(Product.images)).where(Product.id.in_([int(p) for p in product_ids]))
    )
    products_map = {p.id: p for p in result.scalars().all()}
    not_ready = []
    for pid in product_ids:
        product = products_map.get(int(pid))
        if not product:
            not_ready.append({"product_id": int(pid), "problems": ["Товар не найден"]})
            continue
        problems = _get_feed_problems(product)
        if problems:
            not_ready.append({"product_id": int(pid), "title": product.title, "problems": problems})
    if not_ready:
        return JSONResponse({
            "ok": False,
            "error": f"{len(not_ready)} товар(ов) не готовы к публикации",
            "not_ready": not_ready,
        }, status_code=400)

    items = []
    for i, pid in enumerate(product_ids):
        scheduled_at = start_time + timedelta(minutes=interval_minutes * i)

        result = await db.execute(
            select(Listing).where(Listing.product_id == int(pid), Listing.account_id == int(account_id))
        )
        listing = result.scalar_one_or_none()
        if listing:
            listing.status = "scheduled"
            listing.scheduled_at = scheduled_at
        else:
            listing = Listing(
                product_id=int(pid),
                account_id=int(account_id),
                status="scheduled",
                scheduled_at=scheduled_at,
            )
            db.add(listing)

        display_time = scheduled_at.replace(tzinfo=timezone.utc).astimezone(MSK)
        items.append({
            "product_id": int(pid),
            "scheduled_at": display_time.strftime("%d.%m.%Y %H:%M"),
        })

    await db.commit()
    return JSONResponse({"ok": True, "scheduled": len(items), "items": items})
