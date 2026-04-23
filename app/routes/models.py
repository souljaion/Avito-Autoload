from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, and_, exists, func, cast, Date
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

MSK = ZoneInfo("Europe/Moscow")

from app.db import get_db
from app.catalog import (
    get_catalog, DEFAULT_CONDITION, DEFAULT_COLOR,
    DEFAULT_AD_TYPE, DEFAULT_AVAILABILITY, DEFAULT_DELIVERY,
    DEFAULT_DELIVERY_SUBSIDY, DEFAULT_MULTI_ITEM, DEFAULT_TRY_ON,
)
from app.models.account import Account
from app.models.item_stats import ItemStats
from app.models.model import Model
from app.models.photo_pack import PhotoPack
from app.models.listing import Listing
from app.models.product import Product
from app.models.product_image import ProductImage
from app.models.pack_usage_history import PackUsageHistory
from app.models.description_template import DescriptionTemplate
from app.models.variant import ModelVariant

router = APIRouter(prefix="/models", tags=["models"])
templates = Jinja2Templates(directory="app/templates")


def _default_ad_title(model) -> str:
    """Build default ad title from model. Don't duplicate brand if already in name."""
    name = (model.name or "").strip()
    brand = (model.brand or "").strip()
    if not brand:
        return name
    if not name:
        return brand
    if name.lower().startswith(brand.lower() + " ") or name.lower() == brand.lower():
        return name
    return f"{brand} {name}"


@router.get("", response_class=HTMLResponse)
async def model_list(request: Request, db: AsyncSession = Depends(get_db)):
    """Models dashboard with account matrix."""
    stmt = (
        select(Model)
        .options(
            selectinload(Model.products).selectinload(Product.account),
            selectinload(Model.products).selectinload(Product.images),
            selectinload(Model.photo_packs).selectinload(PhotoPack.images),
        )
        .order_by(Model.id.desc())
    )
    result = await db.execute(stmt)
    models = result.scalars().unique().all()

    accs_result = await db.execute(select(Account).order_by(Account.name))
    accounts = accs_result.scalars().all()

    # Build matrix data
    matrix = []
    brands_set = set()
    for m in models:
        row = {"model": m, "cells": {}}
        if m.brand:
            brands_set.add(m.brand)
        for acc in accounts:
            # Find product for this model+account
            product = next(
                (p for p in m.products if p.account_id == acc.id),
                None,
            )
            if product:
                sched_display = None
                if product.scheduled_at:
                    msk_time = product.scheduled_at.replace(tzinfo=timezone.utc).astimezone(MSK)
                    if acc.avito_sync_minute is not None:
                        sh, sm = msk_time.hour, msk_time.minute
                        appear_h = sh if sm <= acc.avito_sync_minute else (sh + 1) % 24
                        sched_display = f"~{appear_h:02d}:{acc.avito_sync_minute:02d}"
                    else:
                        sched_display = msk_time.strftime("%H:%M")
                row["cells"][acc.id] = {
                    "product_id": product.id,
                    "status": product.status,
                    "scheduled_at": sched_display,
                }
            else:
                row["cells"][acc.id] = None
        # First photo from first pack for card preview
        first_img = None
        for pack in m.photo_packs:
            if pack.images:
                sorted_imgs = sorted(pack.images, key=lambda x: x.sort_order)
                first_img = sorted_imgs[0].url
                break
        row["first_image"] = first_img
        active_products = [p for p in m.products if p.status != "removed"]
        row["product_count"] = len(active_products)
        active_prices = [p.price for p in active_products if p.price]
        row["min_price"] = min(active_prices) if active_prices else None
        matrix.append(row)

    catalog = await get_catalog(db)

    return templates.TemplateResponse("models/list.html", {
        "request": request,
        "matrix": matrix,
        "accounts": accounts,
        "brands": sorted(brands_set),
        **catalog,
    })


@router.post("")
async def model_create(
    request: Request,
    name: str = Form(...),
    brand: str = Form(""),
    description: str = Form(""),
    category: str = Form(""),
    goods_type: str = Form(""),
    subcategory: str = Form(""),
    goods_subtype: str = Form(""),
    price: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    from pydantic import ValidationError
    from app.schemas.model import ModelCreateForm
    from app.catalog import requires_subtype

    price_int = None
    if price and price.strip():
        try:
            price_int = int(price)
        except (ValueError, TypeError):
            return JSONResponse({"ok": False, "error": "Цена должна быть числом"}, status_code=400)

    try:
        form = ModelCreateForm(
            name=name, brand=brand, description=description,
            category=category, goods_type=goods_type,
            subcategory=subcategory, goods_subtype=goods_subtype,
            price=price_int,
        )
    except ValidationError as e:
        errors = "; ".join(f"{err['loc'][-1]}: {err['msg']}" for err in e.errors())
        return JSONResponse({"ok": False, "error": errors}, status_code=400)

    if form.subcategory and requires_subtype(form.category, form.goods_type, form.subcategory) and not form.goods_subtype:
        return JSONResponse({"ok": False, "error": "Для этой подкатегории необходимо указать подтип"}, status_code=400)

    m = Model(
        name=form.name,
        brand=form.brand or None,
        description=form.description or None,
        category=form.category or None,
        goods_type=form.goods_type or None,
        subcategory=form.subcategory or None,
        goods_subtype=form.goods_subtype or None,
        price=form.price,
    )
    db.add(m)
    await db.commit()
    if request.headers.get("accept") == "application/json":
        return JSONResponse({"ok": True, "id": m.id, "name": m.name, "brand": m.brand})
    return RedirectResponse(f"/models/{m.id}", status_code=303)


@router.get("/{model_id}", response_class=HTMLResponse)
async def model_detail(request: Request, model_id: int, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(Model)
        .options(
            selectinload(Model.products).selectinload(Product.account),
            selectinload(Model.products).selectinload(Product.images),
            selectinload(Model.photo_packs).selectinload(PhotoPack.images),
        )
        .where(Model.id == model_id)
    )
    result = await db.execute(stmt)
    model = result.scalar_one_or_none()
    if not model:
        return HTMLResponse("Модель не найдена", status_code=404)

    accs_result = await db.execute(select(Account).order_by(Account.name))
    accounts = accs_result.scalars().all()

    catalog = await get_catalog(db)

    # Find which packs have Y.Disk folders (for auto-expand optimization)
    pack_ids = [p.id for p in model.photo_packs]
    packs_with_yd: list[int] = []
    if pack_ids:
        from app.models.photo_pack_yandex_folder import PhotoPackYandexFolder
        yd_result = await db.execute(
            select(PhotoPackYandexFolder.photo_pack_id)
            .where(PhotoPackYandexFolder.photo_pack_id.in_(pack_ids))
            .distinct()
        )
        packs_with_yd = [r[0] for r in yd_result.all()]

    # Load standalone description templates for the dropdown (sorted alphabetically)
    dt_result = await db.execute(
        select(DescriptionTemplate).order_by(DescriptionTemplate.name.asc())
    )
    description_templates = [
        {"id": t.id, "name": t.name}
        for t in dt_result.scalars().all()
    ]

    # Model readiness check
    from app.catalog import requires_subtype
    _required = {
        "brand": "Бренд",
        "category": "Категория",
        "goods_type": "Тип товара",
        "subcategory": "Вид одежды/обуви",
    }
    missing_fields = [ru for key, ru in _required.items() if not getattr(model, key)]
    if not model.goods_subtype and requires_subtype(
        model.category, model.goods_type, model.subcategory
    ):
        missing_fields.append("Подтип")
    model_is_complete = not missing_fields

    return templates.TemplateResponse("models/detail.html", {
        "request": request,
        "model": model,
        "accounts": accounts,
        "packs_with_yd": packs_with_yd,
        "description_templates": description_templates,
        "model_is_complete": model_is_complete,
        "missing_fields": missing_fields,
        **catalog,
    })


@router.post("/{model_id}/add-variant")
async def add_variant(model_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    model = await db.get(Model, model_id)
    if not model:
        return JSONResponse({"ok": False, "error": "Модель не найдена"}, status_code=404)

    body = await request.json()
    product_ids = body.get("product_ids", [])
    # Backward compat: single product_id
    if not product_ids:
        pid = body.get("product_id")
        if pid:
            product_ids = [pid]
    if not product_ids:
        return JSONResponse({"ok": False, "error": "Не указаны product_ids"}, status_code=400)

    result = await db.execute(select(Product).where(Product.id.in_([int(x) for x in product_ids])))
    products = result.scalars().all()
    for p in products:
        p.model_id = model_id
    await db.commit()
    return JSONResponse({"ok": True, "added": len(products)})


@router.post("/{model_id}/copy-variant")
async def copy_variant(model_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    model = await db.get(Model, model_id)
    if not model:
        return JSONResponse({"ok": False, "error": "Модель не найдена"}, status_code=404)

    body = await request.json()
    source_id = body.get("product_id")
    target_account_id = body.get("account_id")

    if not source_id or not target_account_id:
        return JSONResponse({"ok": False, "error": "Не указан product_id или account_id"}, status_code=400)

    stmt = select(Product).options(selectinload(Product.images)).where(Product.id == int(source_id))
    result = await db.execute(stmt)
    source = result.scalar_one_or_none()
    if not source:
        return JSONResponse({"ok": False, "error": "Товар-источник не найден"}, status_code=404)

    copy = Product(
        title=source.title,
        sku=source.sku,
        brand=source.brand,
        model=source.model,
        category=source.category,
        subcategory=source.subcategory,
        goods_type=source.goods_type,
        goods_subtype=source.goods_subtype,
        size=source.size,
        color=source.color,
        material=source.material,
        condition=source.condition,
        price=source.price,
        description=source.description,
        use_custom_description=source.use_custom_description,
        description_template_id=source.description_template_id,
        status="draft",
        account_id=int(target_account_id),
        model_id=model_id,
        image_url=source.image_url,
        extra=dict(source.extra) if source.extra else None,
    )
    db.add(copy)
    await db.flush()

    # Copy images
    for img in source.images:
        new_img = ProductImage(
            product_id=copy.id,
            url=img.url,
            filename=img.filename,
            sort_order=img.sort_order,
            is_main=img.is_main,
        )
        db.add(new_img)

    # Auto-create listing so product is visible on /products page
    db.add(Listing(product_id=copy.id, account_id=int(target_account_id), status="draft"))

    await db.commit()
    return JSONResponse({"ok": True, "new_product_id": copy.id})


@router.post("/{model_id}/detach-variant")
async def detach_variant(model_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    body = await request.json()
    product_id = body.get("product_id")
    if not product_id:
        return JSONResponse({"ok": False, "error": "Не указан product_id"}, status_code=400)

    product = await db.get(Product, int(product_id))
    if not product or product.model_id != model_id:
        return JSONResponse({"ok": False, "error": "Товар не найден в этой модели"}, status_code=404)

    product.model_id = None
    await db.commit()
    return JSONResponse({"ok": True})


@router.post("/{model_id}/update-name")
async def update_name(model_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    model = await db.get(Model, model_id)
    if not model:
        return JSONResponse({"ok": False, "error": "Модель не найдена"}, status_code=404)

    body = await request.json()
    name = body.get("name", "").strip()
    if not name:
        return JSONResponse({"ok": False, "error": "Имя не может быть пустым"}, status_code=400)

    model.name = name
    if "brand" in body:
        model.brand = body["brand"].strip() or None
    await db.commit()
    return JSONResponse({"ok": True})


@router.get("/{model_id}/info")
async def model_info(model_id: int, db: AsyncSession = Depends(get_db)):
    model = await db.get(Model, model_id)
    if not model:
        return JSONResponse({"ok": False}, status_code=404)
    return JSONResponse({
        "name": model.name,
        "brand": model.brand or "",
        "description": model.description or "",
    })


@router.post("/{model_id}/create-variant")
async def create_variant(
    model_id: int,
    request: Request,
    title: str = Form(...),
    brand: str = Form(""),
    price: str = Form("0"),
    size: str = Form(""),
    color: str = Form(""),
    condition: str = Form(""),
    goods_type: str = Form(""),
    subcategory: str = Form(""),
    goods_subtype: str = Form(""),
    account_id: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    model = await db.get(Model, model_id)
    if not model:
        return HTMLResponse("Модель не найдена", status_code=404)

    try:
        price_int = int(price) if price and price.strip() else None
    except (ValueError, TypeError):
        price_int = None

    acct_id = int(account_id) if account_id else None
    product = Product(
        title=title,
        brand=brand or None,
        price=price_int,
        size=size or None,
        color=color or DEFAULT_COLOR,
        condition=condition or DEFAULT_CONDITION,
        goods_type=goods_type or None,
        subcategory=subcategory or None,
        goods_subtype=goods_subtype or None,
        category="Одежда, обувь, аксессуары",
        status="draft",
        account_id=acct_id,
        model_id=model_id,
        extra={
            "ad_type": DEFAULT_AD_TYPE,
            "availability": DEFAULT_AVAILABILITY,
            "delivery": DEFAULT_DELIVERY,
            "delivery_subsidy": DEFAULT_DELIVERY_SUBSIDY,
            "multi_item": DEFAULT_MULTI_ITEM,
            "try_on": DEFAULT_TRY_ON,
        },
    )
    db.add(product)
    await db.flush()

    if acct_id:
        db.add(Listing(product_id=product.id, account_id=acct_id, status="draft"))

    await db.commit()
    return RedirectResponse(f"/models/{model_id}?success=Вариант+создан", status_code=303)


@router.get("/{model_id}/create-all-preview")
async def create_all_preview(model_id: int, db: AsyncSession = Depends(get_db)):
    """Preview what create-all-listings would do."""
    stmt = (
        select(Model)
        .options(
            selectinload(Model.products),
            selectinload(Model.photo_packs).selectinload(PhotoPack.images),
        )
        .where(Model.id == model_id)
    )
    result = await db.execute(stmt)
    model = result.scalar_one_or_none()
    if not model:
        return JSONResponse({"ok": False, "error": "Модель не найдена"}, status_code=404)

    accs_result = await db.execute(select(Account).order_by(Account.name))
    accounts = accs_result.scalars().all()

    packs = [p for p in model.photo_packs if p.images]
    if not packs:
        return JSONResponse({"ok": False, "error": "Нет фотопаков с фото"}, status_code=400)

    existing_account_ids = {
        p.account_id for p in model.products
        if p.status in ("active", "draft", "published", "scheduled", "imported")
        and p.account_id is not None
    }

    # Load pack usage history
    usage_result = await db.execute(select(PackUsageHistory).where(PackUsageHistory.pack_id.in_([p.id for p in packs])))
    usage_records = usage_result.scalars().all()
    used_pairs = {(u.pack_id, u.account_id) for u in usage_records}

    items = []
    for i, acc in enumerate(accounts):
        pack = packs[i % len(packs)]
        needs_uniquify = (pack.id, acc.id) in used_pairs
        if acc.id in existing_account_ids:
            items.append({
                "account_id": acc.id,
                "account": acc.name,
                "pack_id": pack.id,
                "pack_name": pack.name,
                "uniquify": needs_uniquify,
                "action": "skip",
                "reason": "уже существует",
            })
        else:
            items.append({
                "account_id": acc.id,
                "account": acc.name,
                "pack_id": pack.id,
                "pack_name": pack.name,
                "uniquify": needs_uniquify,
                "action": "create",
            })

    return JSONResponse({
        "ok": True,
        "items": items,
        "packs": [{"id": p.id, "name": p.name} for p in packs],
    })


@router.patch("/{model_id}")
async def patch_model(model_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    """Update model fields (name, brand, description)."""
    model = await db.get(Model, model_id)
    if not model:
        return JSONResponse({"ok": False, "error": "Модель не найдена"}, status_code=404)
    body = await request.json()
    if "name" in body:
        name = body["name"].strip()
        if not name:
            return JSONResponse({"ok": False, "error": "Имя не может быть пустым"}, status_code=400)
        model.name = name
    if "brand" in body:
        model.brand = body["brand"].strip() or None
    if "description" in body:
        model.description = body["description"].strip() or None
    for field in ("category", "subcategory", "goods_type", "goods_subtype"):
        if field in body:
            setattr(model, field, body[field].strip() or None)
    await db.commit()
    return JSONResponse({"ok": True, "id": model.id, "name": model.name, "brand": model.brand})


@router.get("/{model_id}/accounts-status")
async def accounts_status(model_id: int, db: AsyncSession = Depends(get_db)):
    """Return status of each account for a given model."""
    model_stmt = (
        select(Model)
        .options(
            selectinload(Model.products).selectinload(Product.account),
            selectinload(Model.products).selectinload(Product.images),
            selectinload(Model.photo_packs),
        )
        .where(Model.id == model_id)
    )
    result = await db.execute(model_stmt)
    model = result.scalar_one_or_none()
    if not model:
        return JSONResponse({"ok": False, "error": "Модель не найдена"}, status_code=404)

    accs_result = await db.execute(select(Account).order_by(Account.name))
    accounts = accs_result.scalars().all()

    # Build pack usage map: product_id -> pack info (from pack usage history)
    pack_ids = [p.id for p in model.photo_packs]
    pack_map = {p.id: p.name for p in model.photo_packs}
    usage_map = {}
    if pack_ids:
        usage_result = await db.execute(
            select(PackUsageHistory).where(PackUsageHistory.pack_id.in_(pack_ids))
        )
        for u in usage_result.scalars().all():
            # Map account_id to pack info from usage
            usage_map[u.account_id] = {"pack_id": u.pack_id, "pack_name": pack_map.get(u.pack_id, "")}

    # --- Compute markers for products (same logic as analytics efficiency) ---
    product_ids = [p.id for p in model.products if p.avito_id is not None]
    markers_map: dict[int, dict] = {}  # product_id -> {marker, views_total, views_today}
    if product_ids:
        cutoff_5d = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=5)
        today = datetime.now(timezone.utc).replace(tzinfo=None).date()
        yesterday = today - timedelta(days=1)

        # 5-day window
        window_result = await db.execute(
            select(
                ItemStats.product_id,
                func.max(ItemStats.views).label("max_views"),
                func.min(ItemStats.views).label("min_views"),
                func.count().label("cnt"),
            )
            .where(ItemStats.captured_at >= cutoff_5d, ItemStats.product_id.in_(product_ids))
            .group_by(ItemStats.product_id)
        )
        window_map = {r.product_id: (r.max_views or 0, r.min_views or 0, r.cnt) for r in window_result.all()}

        # Baseline before window
        baseline_result = await db.execute(
            select(ItemStats.product_id, func.max(ItemStats.views).label("bv"))
            .where(ItemStats.captured_at < cutoff_5d, ItemStats.product_id.in_(product_ids))
            .group_by(ItemStats.product_id)
        )
        baseline_map = {r.product_id: r.bv or 0 for r in baseline_result.all()}

        # Totals
        totals_result = await db.execute(
            select(ItemStats.product_id, func.max(ItemStats.views).label("vt"))
            .where(ItemStats.product_id.in_(product_ids))
            .group_by(ItemStats.product_id)
        )
        totals_map = {r.product_id: r.vt or 0 for r in totals_result.all()}

        # Today / yesterday for delta
        today_result = await db.execute(
            select(ItemStats.product_id, func.max(ItemStats.views).label("v"))
            .where(cast(ItemStats.captured_at, Date) == today, ItemStats.product_id.in_(product_ids))
            .group_by(ItemStats.product_id)
        )
        today_map = {r.product_id: r.v or 0 for r in today_result.all()}

        yesterday_result = await db.execute(
            select(ItemStats.product_id, func.max(ItemStats.views).label("v"))
            .where(cast(ItemStats.captured_at, Date) == yesterday, ItemStats.product_id.in_(product_ids))
            .group_by(ItemStats.product_id)
        )
        yesterday_map = {r.product_id: r.v or 0 for r in yesterday_result.all()}

        for pid in product_ids:
            views_total = totals_map.get(pid)
            views_today = None
            if pid in today_map and pid in yesterday_map:
                views_today = max(0, today_map[pid] - yesterday_map[pid])

            # Marker logic
            w = window_map.get(pid)
            if w is None:
                marker = "unknown"
            else:
                max_v, min_v, cnt = w
                bv = baseline_map.get(pid)
                if bv is not None:
                    delta = max(0, max_v - bv)
                elif cnt >= 2:
                    delta = max(0, max_v - min_v)
                else:
                    delta = None

                if delta is None:
                    marker = "unknown"
                elif delta < 20:
                    marker = "dead"
                elif delta <= 30:
                    marker = "weak"
                else:
                    marker = "alive"

            markers_map[pid] = {
                "marker": marker,
                "views_total": views_total,
                "views_today": views_today,
            }

    items = []
    for acc in accounts:
        product = next(
            (p for p in model.products if p.account_id == acc.id),
            None,
        )
        if product:
            status_val = product.status
            if status_val in ("active", "published", "imported"):
                status_val = "active"
            elif status_val == "scheduled":
                status_val = "scheduled"
            else:
                status_val = "draft"

            pack_info = usage_map.get(acc.id, {})
            m = markers_map.get(product.id, {})

            pub_str = None
            if product.published_at:
                pub_naive = product.published_at.replace(tzinfo=None) if product.published_at.tzinfo else product.published_at
                pub_str = pub_naive.strftime("%d.%m.%Y")

            items.append({
                "account_id": acc.id,
                "account_name": acc.name,
                "product_id": product.id,
                "title": product.title,
                "size": product.size,
                "condition": product.condition,
                "description": product.description,
                "use_custom_description": product.use_custom_description,
                "pack_id": pack_info.get("pack_id"),
                "pack_name": pack_info.get("pack_name", ""),
                "price": product.price,
                "status": status_val,
                "scheduled_at": product.scheduled_at.replace(tzinfo=timezone.utc).astimezone(MSK).strftime("%d.%m %H:%M") if product.scheduled_at else None,
                "avito_id": product.avito_id,
                "avito_sync_minute": acc.avito_sync_minute,
                "marker": m.get("marker", "unknown"),
                "views_total": m.get("views_total"),
                "views_today": m.get("views_today"),
                "published_at": pub_str,
                "variant_id": product.variant_id,
            })
        else:
            items.append({
                "account_id": acc.id,
                "account_name": acc.name,
                "product_id": None,
                "pack_id": None,
                "pack_name": None,
                "price": None,
                "status": "none",
                "scheduled_at": None,
                "avito_id": None,
                "avito_sync_minute": acc.avito_sync_minute,
                "marker": None,
                "views_total": None,
                "views_today": None,
                "published_at": None,
                "variant_id": None,
            })

    has_dead = any(i["marker"] == "dead" for i in items)
    return JSONResponse({"ok": True, "items": items, "has_dead": has_dead})


@router.get("/{model_id}/analytics")
async def model_analytics(model_id: int, db: AsyncSession = Depends(get_db)):
    """Efficiency analytics for a model's active products."""
    model = await db.get(Model, model_id)
    if not model:
        return JSONResponse({"ok": False, "error": "Модель не найдена"}, status_code=404)

    result = await db.execute(
        select(Product)
        .options(selectinload(Product.account))
        .where(
            Product.model_id == model_id,
            Product.status.in_(["active", "imported", "published"]),
        )
        .order_by(Product.id.desc())
    )
    products = result.scalars().all()

    if not products:
        return JSONResponse({
            "ok": True,
            "items": [],
            "recommendations": {
                "dead_count": 0, "weak_count": 0, "live_count": 0,
                "recommendation": "Нет активных объявлений по этой модели",
            },
        })

    product_ids = [p.id for p in products]

    # 5-day window for marker calculation (same logic as analytics efficiency)
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=5)

    window_stmt = (
        select(
            ItemStats.product_id,
            func.max(ItemStats.views).label("max_views"),
            func.min(ItemStats.views).label("min_views"),
            func.count().label("cnt"),
        )
        .where(ItemStats.captured_at >= cutoff, ItemStats.product_id.in_(product_ids))
        .group_by(ItemStats.product_id)
    )
    window_result = await db.execute(window_stmt)
    window_map = {r.product_id: (r.max_views or 0, r.min_views or 0, r.cnt) for r in window_result.all()}

    baseline_stmt = (
        select(
            ItemStats.product_id,
            func.max(ItemStats.views).label("baseline_views"),
        )
        .where(ItemStats.captured_at < cutoff, ItemStats.product_id.in_(product_ids))
        .group_by(ItemStats.product_id)
    )
    baseline_result = await db.execute(baseline_stmt)
    baseline_map = {r.product_id: r.baseline_views or 0 for r in baseline_result.all()}

    views_5d_map = {}
    single_snapshot = set()
    for pid, (max_v, min_v, cnt) in window_map.items():
        baseline_v = baseline_map.get(pid)
        if baseline_v is not None:
            views_5d_map[pid] = max(0, max_v - baseline_v)
        elif cnt >= 2:
            views_5d_map[pid] = max(0, max_v - min_v)
        else:
            views_5d_map[pid] = None
            single_snapshot.add(pid)

    # Totals
    totals_stmt = (
        select(
            ItemStats.product_id,
            func.max(ItemStats.views).label("views_total"),
            func.max(ItemStats.contacts).label("contacts_total"),
        )
        .where(ItemStats.product_id.in_(product_ids))
        .group_by(ItemStats.product_id)
    )
    totals_result = await db.execute(totals_stmt)
    totals_map = {r.product_id: (r.views_total or 0, r.contacts_total or 0) for r in totals_result.all()}

    # Today deltas
    today = datetime.now(timezone.utc).replace(tzinfo=None).date()
    yesterday = today - timedelta(days=1)

    today_stmt = (
        select(ItemStats.product_id, func.max(ItemStats.views).label("v"))
        .where(cast(ItemStats.captured_at, Date) == today, ItemStats.product_id.in_(product_ids))
        .group_by(ItemStats.product_id)
    )
    today_result = await db.execute(today_stmt)
    today_map = {r.product_id: r.v or 0 for r in today_result.all()}

    yesterday_stmt = (
        select(ItemStats.product_id, func.max(ItemStats.views).label("v"))
        .where(cast(ItemStats.captured_at, Date) == yesterday, ItemStats.product_id.in_(product_ids))
        .group_by(ItemStats.product_id)
    )
    yesterday_result = await db.execute(yesterday_stmt)
    yesterday_map = {r.product_id: r.v or 0 for r in yesterday_result.all()}

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    items = []
    dead_count = 0
    weak_count = 0
    live_count = 0

    for p in products:
        # Marker
        if p.id in single_snapshot:
            marker = "unknown"
        elif p.id in views_5d_map:
            v = views_5d_map[p.id]
            if v is None:
                marker = "unknown"
            elif v < 20:
                marker = "dead"
            elif v <= 30:
                marker = "weak"
            else:
                marker = "alive"
        else:
            marker = "unknown"

        if marker == "dead":
            dead_count += 1
        elif marker == "weak":
            weak_count += 1
        elif marker == "alive":
            live_count += 1

        vt, ct = totals_map.get(p.id, (None, None))

        views_delta = None
        if p.id in today_map and p.id in yesterday_map:
            views_delta = max(0, today_map[p.id] - yesterday_map[p.id])

        days_active = None
        if p.published_at:
            pub_naive = p.published_at.replace(tzinfo=None) if p.published_at.tzinfo else p.published_at
            days_active = (now - pub_naive).days

        items.append({
            "id": p.id,
            "title": p.title,
            "account_name": p.account.name if p.account else None,
            "avito_id": p.avito_id,
            "marker": marker,
            "views_total": vt,
            "views_delta": views_delta,
            "contacts_total": ct,
            "days_active": days_active,
        })

    # Recommendation
    total_active = len(products)
    if total_active == 0:
        recommendation = "Нет активных объявлений по этой модели"
    elif dead_count == 0 and weak_count == 0 and live_count > 0:
        recommendation = "Всё хорошо — модель продаётся активно"
    elif dead_count > 0:
        recommendation = f"Есть {dead_count} мёртвых объявлений — рекомендуется перевыложить"
    elif weak_count > 0:
        recommendation = f"Есть {weak_count} слабых объявлений — попробуйте перевыложить"
    else:
        recommendation = "Всё хорошо — модель продаётся активно"

    return JSONResponse({
        "ok": True,
        "items": items,
        "recommendations": {
            "dead_count": dead_count,
            "weak_count": weak_count,
            "live_count": live_count,
            "recommendation": recommendation,
        },
    })


@router.get("/{model_id}/history")
async def model_history(model_id: int, db: AsyncSession = Depends(get_db)):
    """Publication history for a model's products."""
    result = await db.execute(
        select(Product)
        .options(selectinload(Product.account))
        .where(
            Product.model_id == model_id,
            Product.published_at.isnot(None),
        )
        .order_by(Product.published_at.desc())
        .limit(10)
    )
    products = result.scalars().all()
    if not products:
        return JSONResponse({"ok": True, "items": []})

    product_ids = [p.id for p in products]

    # Latest stats per product
    stats_result = await db.execute(
        select(
            ItemStats.product_id,
            func.max(ItemStats.views).label("views"),
            func.max(ItemStats.contacts).label("contacts"),
        )
        .where(ItemStats.product_id.in_(product_ids))
        .group_by(ItemStats.product_id)
    )
    stats_map = {r.product_id: (r.views or 0, r.contacts or 0) for r in stats_result.all()}

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    items = []
    for p in products:
        pub_naive = p.published_at.replace(tzinfo=None) if p.published_at.tzinfo else p.published_at
        days_active = (now - pub_naive).days
        views, contacts = stats_map.get(p.id, (0, 0))
        items.append({
            "product_id": p.id,
            "account_name": p.account.name if p.account else None,
            "status": p.status,
            "published_at": pub_naive.strftime("%d.%m.%Y"),
            "days_active": days_active,
            "views": views,
            "contacts": contacts,
        })

    return JSONResponse({"ok": True, "items": items})


@router.post("/{model_id}/products")
async def create_model_product(model_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    """Create a draft product for a model from the listings table."""
    from app.routes.products import _apply_pack_to_product

    model = await db.get(Model, model_id)
    if not model:
        return JSONResponse({"ok": False, "error": "Модель не найдена"}, status_code=404)

    body = await request.json()
    account_id = body.get("account_id")
    if not account_id:
        return JSONResponse({"ok": False, "error": "account_id обязателен"}, status_code=400)

    # Title: use explicit value from request, or auto-generate from model
    title = (body.get("title") or "").strip() or _default_ad_title(model)

    # description_template_id from request (if provided)
    desc_tpl_id = body.get("description_template_id")
    if desc_tpl_id is not None:
        desc_tpl_id = int(desc_tpl_id)

    # pack_id from request (if provided) — Bug #5 fix
    pack_id = body.get("pack_id")
    if pack_id is not None:
        pack_id = int(pack_id)

    # Copy description and price from model; explicit values override
    has_model_desc = bool(model.description)

    product = Product(
        title=title,
        brand=model.brand or None,
        status="draft",
        account_id=int(account_id),
        model_id=model_id,
        category=model.category or "Одежда, обувь, аксессуары",
        subcategory=model.subcategory,
        goods_type=model.goods_type,
        goods_subtype=model.goods_subtype,
        condition=DEFAULT_CONDITION,
        color=DEFAULT_COLOR,
        description=model.description if has_model_desc else None,
        use_custom_description=has_model_desc,
        description_template_id=desc_tpl_id,
        size=body.get("size") or None,
        price=int(body["price"]) if body.get("price") else model.price,
        pack_id=pack_id,
        extra={
            "ad_type": DEFAULT_AD_TYPE,
            "availability": DEFAULT_AVAILABILITY,
            "delivery": DEFAULT_DELIVERY,
            "delivery_subsidy": DEFAULT_DELIVERY_SUBSIDY,
            "multi_item": DEFAULT_MULTI_ITEM,
            "try_on": DEFAULT_TRY_ON,
        },
    )
    db.add(product)
    # Flush to get product.id before applying pack (ProductImage FK needs it)
    await db.flush()

    # Apply pack photos if specified (Bug #5: was missing before)
    if pack_id is not None:
        await _apply_pack_to_product(db, product.id, pack_id, do_uniquify=False)

    db.add(Listing(product_id=product.id, account_id=int(account_id), status="draft"))
    await db.commit()

    return JSONResponse({
        "ok": True,
        "product_id": product.id,
        "title": product.title,
        "status": product.status,
    })



# ── Bulk actions from matrix ──

@router.post("/{model_id}/bulk-schedule")
async def bulk_schedule(model_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    """Move selected drafts to status=scheduled without scheduled_at or readiness check.

    Operator will set time later on /schedule/{account_id}.
    """
    body = await request.json()
    product_ids = body.get("product_ids", [])
    if not product_ids:
        return JSONResponse({"ok": False, "error": "Не выбраны объявления"}, status_code=400)

    int_ids = [int(p) for p in product_ids]

    result = await db.execute(
        select(Product).where(Product.id.in_(int_ids), Product.model_id == model_id)
    )
    products = result.scalars().all()

    scheduled = []
    skipped = []
    for product in products:
        if product.status != "draft":
            skipped.append({"id": product.id, "reason": f"status={product.status}, нужен draft"})
            continue

        product.status = "scheduled"
        product.scheduled_at = None

        # Sync listing status
        listing_result = await db.execute(
            select(Listing).where(Listing.product_id == product.id)
        )
        for listing in listing_result.scalars().all():
            listing.status = "scheduled"
            listing.scheduled_at = None

        scheduled.append(product.id)

    await db.commit()
    return JSONResponse({
        "ok": True,
        "scheduled": scheduled,
        "skipped": skipped,
    })


@router.post("/{model_id}/bulk-publish")
async def bulk_publish(model_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    """Bulk publish drafts from the matrix. Sets status=scheduled with scheduled_at=now.

    Products must be draft and ready for feed. Returns per-product results.
    """
    from datetime import datetime as dt, timezone
    from app.services.feed_generator import get_missing_fields
    from app.models.account_description_template import AccountDescriptionTemplate as ADT

    body = await request.json()
    product_ids = body.get("product_ids", [])
    if not product_ids:
        return JSONResponse({"ok": False, "error": "Не выбраны объявления"}, status_code=400)

    int_ids = [int(p) for p in product_ids]

    result = await db.execute(
        select(Product)
        .options(selectinload(Product.images))
        .where(Product.id.in_(int_ids))
    )
    products = {p.id: p for p in result.scalars().all()}

    # Prefetch ADTs for all relevant accounts (1 query instead of N)
    unique_account_ids = {p.account_id for p in products.values() if p.account_id}
    adt_set: set[int] = set()
    if unique_account_ids:
        adt_result = await db.execute(
            select(ADT.account_id).where(ADT.account_id.in_(unique_account_ids))
        )
        adt_set = {row[0] for row in adt_result.all()}

    # Prefetch existing listings for all products (1 query instead of N)
    listings_result = await db.execute(
        select(Listing).where(
            Listing.product_id.in_(int_ids),
        )
    )
    listings_map: dict[tuple[int, int], Listing] = {
        (ls.product_id, ls.account_id): ls for ls in listings_result.scalars().all()
    }

    now = dt.now(timezone.utc).replace(tzinfo=None)
    published = []
    not_ready = []
    skipped = []

    for pid in product_ids:
        pid = int(pid)
        product = products.get(pid)
        if not product:
            skipped.append({"product_id": pid, "reason": "Не найден"})
            continue
        if product.status != "draft":
            skipped.append({"product_id": pid, "reason": f"Статус: {product.status}"})
            continue

        has_acct_tpl = product.account_id in adt_set

        missing = get_missing_fields(product, has_account_template=has_acct_tpl)
        if missing:
            not_ready.append({"product_id": pid, "title": product.title, "missing": missing})
            continue

        # Set product status
        product.status = "scheduled"
        product.scheduled_at = now

        # Find or create listing
        listing = listings_map.get((pid, product.account_id))
        if listing:
            listing.status = "scheduled"
            listing.scheduled_at = now
        else:
            db.add(Listing(
                product_id=pid,
                account_id=product.account_id,
                status="scheduled",
                scheduled_at=now,
            ))

        published.append(pid)

    await db.commit()
    return JSONResponse({
        "ok": True,
        "published": len(published),
        "published_ids": published,
        "not_ready": not_ready,
        "skipped": skipped,
    })


# ── Link existing products ──

@router.get("/{model_id}/unlinked-products")
async def unlinked_products(
    model_id: int,
    q: str = "",
    account_id: int | None = None,
    count_only: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """Search products without a model for linking."""
    if count_only:
        count_stmt = (
            select(func.count(Product.id))
            .where(
                Product.model_id.is_(None),
                Product.status.in_(["imported", "active", "published", "draft"]),
            )
        )
        result = await db.execute(count_stmt)
        return JSONResponse({"ok": True, "count": result.scalar() or 0})

    stmt = (
        select(Product)
        .options(selectinload(Product.account), selectinload(Product.images))
        .where(
            Product.model_id.is_(None),
            Product.status.in_(["imported", "active", "published", "draft"]),
        )
        .order_by(Product.id.desc())
        .limit(1000)
    )

    if q and q.strip():
        for word in q.strip().split():
            stmt = stmt.where(Product.title.ilike(f"%{word}%"))

    if account_id:
        stmt = stmt.where(Product.account_id == account_id)

    result = await db.execute(stmt)
    products = result.scalars().all()

    # Get latest views per product from item_stats
    pids = [p.id for p in products if p.avito_id]
    views_map: dict[int, int] = {}
    if pids:
        stats_result = await db.execute(
            select(ItemStats.product_id, func.max(ItemStats.views).label("v"))
            .where(ItemStats.product_id.in_(pids))
            .group_by(ItemStats.product_id)
        )
        views_map = {r.product_id: r.v or 0 for r in stats_result.all()}

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
            "status": p.status,
            "size": p.size,
            "price": p.price,
            "avito_id": p.avito_id,
            "views": views_map.get(p.id),
            "image_url": image_url,
        })

    return JSONResponse({"ok": True, "items": items})


@router.post("/{model_id}/link-products")
async def link_products(model_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    """Link existing products to this model."""
    model = await db.get(Model, model_id)
    if not model:
        return JSONResponse({"ok": False, "error": "Модель не найдена"}, status_code=404)

    body = await request.json()
    product_ids = body.get("product_ids", [])
    if not product_ids:
        return JSONResponse({"ok": False, "error": "Не указаны product_ids"}, status_code=400)

    result = await db.execute(
        select(Product).where(
            Product.id.in_([int(x) for x in product_ids]),
            Product.model_id.is_(None),
        )
    )
    products = result.scalars().all()
    for p in products:
        p.model_id = model_id
    await db.commit()
    return JSONResponse({"ok": True, "linked": len(products)})


# ── Variant CRUD ──

@router.post("/{model_id}/variants")
async def create_variant_api(model_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    model = await db.get(Model, model_id)
    if not model:
        return JSONResponse({"ok": False, "error": "Модель не найдена"}, status_code=404)

    body = await request.json()
    name = (body.get("name") or "").strip()
    if not name:
        return JSONResponse({"ok": False, "error": "Название обязательно"}, status_code=400)

    variant = ModelVariant(
        model_id=model_id,
        name=name,
        size=(body.get("size") or "").strip() or None,
        price=int(body["price"]) if body.get("price") else None,
        pack_id=int(body["pack_id"]) if body.get("pack_id") else None,
    )
    db.add(variant)
    await db.commit()
    return JSONResponse({
        "ok": True,
        "id": variant.id,
        "name": variant.name,
        "size": variant.size,
        "price": variant.price,
        "pack_id": variant.pack_id,
    })


@router.put("/{model_id}/variants/{variant_id}")
async def update_variant_api(model_id: int, variant_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    variant = await db.get(ModelVariant, variant_id)
    if not variant or variant.model_id != model_id:
        return JSONResponse({"ok": False, "error": "Вариант не найден"}, status_code=404)

    body = await request.json()
    if "name" in body:
        name = (body["name"] or "").strip()
        if not name:
            return JSONResponse({"ok": False, "error": "Название обязательно"}, status_code=400)
        variant.name = name
    if "size" in body:
        variant.size = (body["size"] or "").strip() or None
    if "price" in body:
        variant.price = int(body["price"]) if body["price"] else None
    if "pack_id" in body:
        variant.pack_id = int(body["pack_id"]) if body["pack_id"] else None

    await db.commit()
    return JSONResponse({
        "ok": True,
        "id": variant.id,
        "name": variant.name,
        "size": variant.size,
        "price": variant.price,
        "pack_id": variant.pack_id,
    })


@router.delete("/{model_id}/variants/{variant_id}")
async def delete_variant_api(model_id: int, variant_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ModelVariant)
        .options(selectinload(ModelVariant.products))
        .where(ModelVariant.id == variant_id, ModelVariant.model_id == model_id)
    )
    variant = result.scalar_one_or_none()
    if not variant:
        return JSONResponse({"ok": False, "error": "Вариант не найден"}, status_code=404)

    active_products = [p for p in variant.products if p.status in ("active", "published", "scheduled")]
    if active_products:
        return JSONResponse(
            {"ok": False, "error": "Нельзя удалить вариант с активными объявлениями"},
            status_code=400,
        )

    for p in variant.products:
        p.variant_id = None
    await db.delete(variant)
    await db.commit()
    return JSONResponse({"ok": True})


@router.delete("/{model_id}")
async def delete_model(model_id: int, db: AsyncSession = Depends(get_db)):
    stmt = select(Model).options(selectinload(Model.products)).where(Model.id == model_id)
    result = await db.execute(stmt)
    model = result.scalar_one_or_none()
    if not model:
        return JSONResponse({"ok": False, "error": "Модель не найдена"}, status_code=404)

    # Detach products (don't delete them)
    for p in model.products:
        p.model_id = None

    await db.delete(model)
    await db.commit()
    return JSONResponse({"ok": True})
