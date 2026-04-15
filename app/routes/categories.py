import structlog
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.account import Account
from app.models.avito_category import AvitoCategory
from app.services.avito_client import AvitoClient
from app.services.category_sync import sync_tree, sync_fields, FieldsUnavailable

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/categories", tags=["categories"])
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
async def category_list(request: Request, db: AsyncSession = Depends(get_db)):
    """Show synced categories and sync controls."""
    result = await db.execute(select(func.count(AvitoCategory.id)))
    total = result.scalar() or 0

    roots = await db.execute(
        select(AvitoCategory)
        .where(AvitoCategory.parent_id.is_(None))
        .order_by(AvitoCategory.name)
    )
    root_cats = roots.scalars().all()

    tree = []
    for root in root_cats:
        children_result = await db.execute(
            select(AvitoCategory)
            .where(AvitoCategory.parent_id == root.id)
            .order_by(AvitoCategory.name)
        )
        children = children_result.scalars().all()

        child_items = []
        for child in children:
            gc_result = await db.execute(
                select(AvitoCategory)
                .where(AvitoCategory.parent_id == child.id)
                .order_by(AvitoCategory.name)
            )
            grandchildren = gc_result.scalars().all()
            child_items.append({
                "cat": child,
                "children": [{"cat": gc} for gc in grandchildren],
            })

        tree.append({
            "cat": root,
            "children": child_items,
        })

    accs = await db.execute(select(Account).order_by(Account.name))
    accounts = accs.scalars().all()

    return templates.TemplateResponse("categories/list.html", {"page_title": "Категории",
        "request": request,
        "total": total,
        "tree": tree,
        "accounts": accounts,
    })


@router.post("/sync-tree")
async def do_sync_tree(
    request: Request,
    account_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Sync category tree from Avito API using the selected account."""
    account = await db.get(Account, account_id)
    if not account:
        return HTMLResponse("Аккаунт не найден", status_code=404)

    client = AvitoClient(account, db)
    try:
        count = await sync_tree(client, db)
        logger.info("Synced %d categories from account %s", count, account.name)
    except Exception as e:
        logger.exception("Failed to sync tree")
        await db.rollback()
        return RedirectResponse(
            f"/categories?error=Ошибка синхронизации дерева: {e}",
            status_code=303,
        )
    finally:
        await client.close()

    return RedirectResponse(
        f"/categories?success=Загружено категорий: {count}",
        status_code=303,
    )


@router.post("/sync-fields")
async def do_sync_fields(
    request: Request,
    account_id: int = Form(...),
    slug: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Sync fields for a specific category node."""
    account = await db.get(Account, account_id)
    if not account:
        return HTMLResponse("Аккаунт не найден", status_code=404)

    client = AvitoClient(account, db)
    try:
        ok = await sync_fields(client, db, slug)
        if not ok:
            return RedirectResponse(
                f"/categories?error=Категория не найдена: {slug}",
                status_code=303,
            )
    except FieldsUnavailable as e:
        return RedirectResponse(
            f"/categories?error={e}",
            status_code=303,
        )
    except Exception as e:
        logger.exception("Failed to sync fields for %s", slug)
        await db.rollback()
        return RedirectResponse(
            f"/categories?error=Ошибка загрузки полей ({slug}): {e}",
            status_code=303,
        )
    finally:
        await client.close()

    return RedirectResponse(
        f"/categories?success=Поля загружены для: {slug}",
        status_code=303,
    )
