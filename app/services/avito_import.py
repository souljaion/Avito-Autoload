"""Import new ads from Avito for all accounts."""

from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import safe_update_status
from app.models.account import Account
from app.models.listing import Listing
from app.models.product import Product
from app.services.avito_client import AvitoClient

logger = structlog.get_logger(__name__)


async def import_account_items(account: Account, db: AsyncSession) -> dict:
    """Import new items from Avito for a single account."""
    client = AvitoClient(account, db)
    try:
        avito_items = await client.get_user_items(status="active")
    except Exception as e:
        logger.error("avito_import.api_error", account=account.name, error=str(e))
        await client.close()
        return {"account": account.name, "error": str(e)}

    # Set of avito_ids currently active on Avito
    active_avito_ids = set()
    for item in avito_items:
        aid = item.get("id")
        if aid:
            active_avito_ids.add(int(aid))

    # --- Diagnostic logging ---
    sample_ids = sorted(active_avito_ids)[:5]
    logger.info("avito_import.fetched",
                account=account.name,
                account_id=account.id,
                avito_count=len(active_avito_ids),
                sample_avito_ids=sample_ids)

    try:
        # --- Import new items / update existing ---
        existing_result = await db.execute(
            select(Product).where(
                Product.avito_id.isnot(None),
                Product.account_id == account.id,
            )
        )
        existing_products = {p.avito_id: p for p in existing_result.scalars().all()}

        # Also collect all avito_ids across all accounts to avoid cross-account dupes
        all_avito_result = await db.execute(
            select(Product.avito_id).where(Product.avito_id.isnot(None))
        )
        all_avito_ids = {row[0] for row in all_avito_result.all()}

        imported = 0
        updated = 0
        for item in avito_items:
            avito_id = item.get("id")
            if not avito_id:
                continue
            avito_id = int(avito_id)

            cat = item.get("category") or {}
            title = item.get("title", "")
            price = item.get("price")
            description = item.get("description")
            category_name = cat.get("name")

            # Update existing product
            if avito_id in existing_products:
                p = existing_products[avito_id]
                if title:
                    p.title = title
                if price is not None:
                    p.price = price
                if description and not p.description:
                    p.description = description
                if category_name and not p.category:
                    p.category = category_name
                # If product was sold/removed but is still active on Avito, restore it
                # But skip if manually removed (has removed_at set)
                if p.status in ("sold", "removed"):
                    if p.removed_at is not None:
                        logger.info("avito_import.skip_manual_removal",
                                    product_id=p.id, avito_id=avito_id)
                        updated += 1
                        continue
                    success = await safe_update_status(
                        db, p.id, "imported", p.version,
                        extra_fields={"removed_at": None},
                    )
                    if not success:
                        logger.warning("avito_import.skipped_conflict", product_id=p.id)
                        updated += 1
                        continue
                    p.version += 1
                    logger.info("avito_import.restored",
                                account=account.name, product_id=p.id,
                                avito_id=avito_id, old_status=p.status)
                updated += 1
                continue

            # Skip if exists on another account
            if avito_id in all_avito_ids:
                continue

            product = Product(
                avito_id=avito_id,
                feed_ad_id=str(avito_id),
                title=title,
                price=price,
                description=description,
                category=category_name,
                status="imported",
                account_id=account.id,
                published_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
            db.add(product)
            await db.flush()
            db.add(Listing(product_id=product.id, account_id=account.id, status="draft"))
            all_avito_ids.add(avito_id)
            imported += 1

        # --- Mark stale items as removed ---
        stale_result = await db.execute(
            select(Product).where(
                Product.account_id == account.id,
                Product.avito_id.isnot(None),
                Product.status.in_(["active", "published", "imported"]),
            )
        )
        stale_products = stale_result.scalars().all()

        # Diagnostic: type comparison check
        if stale_products and active_avito_ids:
            sample_db = stale_products[0].avito_id
            sample_api = next(iter(active_avito_ids))
            logger.info("avito_import.type_check",
                        account=account.name,
                        db_avito_id_type=type(sample_db).__name__,
                        db_avito_id_sample=sample_db,
                        api_avito_id_type=type(sample_api).__name__,
                        api_avito_id_sample=sample_api)

        # --- Mark stale items as REMOVED (was: sold) ---
        # status=removed + removed_at → товар уйдёт из всех списков и через 48ч
        # будет физически удалён джобом cleanup_removed. Если есть avito_id —
        # попадёт в фид как Status=Removed, но это безвредно: на Авито он уже снят.
        now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        marked_removed = 0
        for p in stale_products:
            avito_id_int = int(p.avito_id) if p.avito_id is not None else None
            if avito_id_int not in active_avito_ids:
                p.status = "removed"
                p.removed_at = now_naive
                marked_removed += 1

        logger.info("avito_import.cleanup",
                    account=account.name,
                    account_id=account.id,
                    avito_count=len(active_avito_ids),
                    db_active_imported=len(stale_products),
                    marked_removed=marked_removed,
                    new_imported=imported,
                    updated=updated)

        await db.commit()
        await client.close()
        return {
            "account": account.name,
            "imported": imported,
            "updated": updated,
            "marked_removed": marked_removed,
            "total": len(avito_items),
        }

    except Exception as e:
        await db.rollback()
        await client.close()
        logger.exception("avito_import.failed", account_id=account.id, error=str(e))
        return {"account": account.name, "error": str(e)}


async def import_all_accounts(db: AsyncSession) -> list[dict]:
    """Import new items from all accounts with autoload enabled."""
    result = await db.execute(
        select(Account).where(
            Account.autoload_enabled == True,
            Account.client_id.isnot(None),
        ).order_by(Account.id)
    )
    accounts = result.scalars().all()

    results = []
    for acc in accounts:
        r = await import_account_items(acc, db)
        results.append(r)
        if "error" not in r and r["imported"] > 0:
            logger.info("Import: %s — %d new / %d total", acc.name, r["imported"], r["total"])

    return results
