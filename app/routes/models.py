from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.catalog import get_catalog, DEFAULT_CONDITION
from app.models.account import Account
from app.models.model import Model
from app.models.photo_pack import PhotoPack
from app.models.product import Product
from app.models.product_image import ProductImage

router = APIRouter(prefix="/models", tags=["models"])
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
async def model_list(request: Request, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(Model)
        .options(selectinload(Model.products).selectinload(Product.account))
        .order_by(Model.id.desc())
    )
    result = await db.execute(stmt)
    models = result.scalars().unique().all()

    model_data = []
    for m in models:
        accounts = {}
        for p in m.products:
            if p.account:
                accounts[p.account.id] = p.account.name
        model_data.append({
            "model": m,
            "variant_count": len(m.products),
            "accounts": list(accounts.values()),
        })

    return templates.TemplateResponse("models/list.html", {
        "request": request,
        "model_data": model_data,
    })


@router.post("")
async def model_create(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    from pydantic import ValidationError
    from app.schemas.model import ModelCreateForm
    try:
        form = ModelCreateForm(name=name, description=description)
    except ValidationError as e:
        errors = "; ".join(f"{err['loc'][-1]}: {err['msg']}" for err in e.errors())
        return JSONResponse({"ok": False, "error": errors}, status_code=400)
    m = Model(name=form.name, description=form.description or None)
    db.add(m)
    await db.commit()
    if request.headers.get("accept") == "application/json":
        return JSONResponse({"ok": True, "id": m.id, "name": m.name})
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

    # Unassigned products for the modal
    unassigned_stmt = (
        select(Product)
        .options(selectinload(Product.account), selectinload(Product.images))
        .where(Product.model_id.is_(None))
        .order_by(Product.id.desc())
        .limit(200)
    )
    unassigned_result = await db.execute(unassigned_stmt)
    unassigned = unassigned_result.scalars().all()

    # Accounts for copy variant
    accs_result = await db.execute(select(Account).order_by(Account.name))
    accounts = accs_result.scalars().all()

    catalog = await get_catalog(db)

    return templates.TemplateResponse("models/detail.html", {
        "request": request,
        "model": model,
        "unassigned": unassigned,
        "accounts": accounts,
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
    await db.commit()
    return JSONResponse({"ok": True})


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

    product = Product(
        title=title,
        brand=brand or None,
        price=price_int,
        size=size or None,
        color=color or None,
        condition=condition or DEFAULT_CONDITION,
        goods_type=goods_type or None,
        subcategory=subcategory or None,
        goods_subtype=goods_subtype or None,
        category="Одежда, обувь, аксессуары",
        status="draft",
        account_id=int(account_id) if account_id else None,
        model_id=model_id,
    )
    db.add(product)
    await db.commit()
    return RedirectResponse(f"/models/{model_id}?success=Вариант+создан", status_code=303)


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
