import os
import shutil

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
from app.models.product import Product
from app.models.product_image import ProductImage
from app.models.model import Model
from app.models.photo_pack_image import PhotoPackImage
from app.schemas.product import ProductCreateForm
from app.services.avito_client import AvitoClient
from app.services.photo_uniquifier import uniquify_image

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

PRODUCT_STATUSES = ["draft", "imported", "active", "paused", "sold", "scheduled", "published"]

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
        account_id=int(account_id) if account_id else None,
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
    return templates.TemplateResponse("products/detail.html", {"request": request, "product": product})


@router.get("/{product_id}/edit", response_class=HTMLResponse)
async def product_edit(request: Request, product_id: int, db: AsyncSession = Depends(get_db)):
    product = await db.get(Product, product_id)
    if not product:
        return HTMLResponse("Товар не найден", status_code=404)
    accs = await db.execute(select(Account).order_by(Account.name))
    models = await db.execute(select(Model).order_by(Model.name))
    catalog = await get_catalog(db)
    return templates.TemplateResponse("products/form.html", {
        "request": request, "product": product, "accounts": accs.scalars().all(),
        "models": models.scalars().all(),
        "statuses": PRODUCT_STATUSES,
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
        status="draft",
        account_id=product.account_id,
        extra=dict(product.extra) if product.extra else None,
    )
    db.add(copy)
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
        product.status = val

    await db.commit()
    return JSONResponse({"ok": True, "id": product.id, "price": product.price, "status": product.status})


@router.delete("/{product_id}")
async def delete_product(product_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Product).options(selectinload(Product.images)).where(Product.id == product_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        return JSONResponse({"ok": False, "error": "Товар не найден"}, status_code=404)

    # Delete images from DB (cascade should handle it, but be explicit)
    for img in product.images:
        await db.delete(img)

    # Delete media folder from disk
    product_dir = os.path.join(settings.MEDIA_DIR, "products", str(product_id))
    if os.path.isdir(product_dir):
        shutil.rmtree(product_dir, ignore_errors=True)

    await db.delete(product)
    await db.commit()
    return JSONResponse({"ok": True})


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
            data = uniquify_image(pimg.file_path)
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
