"""
Detect sold/closed items on Avito and update local product status to 'sold'.

Compares active Avito listings against local products. If a product has an avito_id
but that ID is no longer in the active listings, the product is marked as 'sold'.
"""

from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import safe_update_status
from app.models.account import Account
from app.models.product import Product
from app.services.avito_client import AvitoClient

logger = structlog.get_logger(__name__)


async def check_and_mark_sold(db: AsyncSession, account: Account) -> dict:
    """Check account's Avito items and mark missing ones as sold.

    Returns dict with counts: checked, marked_sold.
    """
    client = AvitoClient(account, db)
    try:
        avito_items = await client.get_user_items(status="active")
    except Exception as e:
        logger.warning("Failed to fetch items for sold detection",
                       account_id=account.id, error=str(e))
        return {"checked": 0, "marked_sold": 0, "error": str(e)}
    finally:
        await client.close()

    # Set of active avito_ids from API
    active_avito_ids = set()
    for item in avito_items:
        aid = item.get("id")
        if aid:
            active_avito_ids.add(int(aid))

    # Local products that should be on Avito
    result = await db.execute(
        select(Product)
        .where(
            Product.account_id == account.id,
            Product.avito_id.isnot(None),
            Product.status.in_(["active", "published"]),
        )
    )
    products = result.scalars().all()

    marked_sold = 0
    for product in products:
        if int(product.avito_id) not in active_avito_ids:
            extra = dict(product.extra) if product.extra else {}
            extra["sold_at"] = datetime.now(timezone.utc).isoformat()
            success = await safe_update_status(
                db, product.id, "sold", product.version,
                extra_fields={"extra": extra},
            )
            if not success:
                logger.warning("sold_detection.skipped_conflict", product_id=product.id)
                continue
            product.version += 1
            marked_sold += 1
            logger.info("Product marked as sold",
                        product_id=product.id, avito_id=product.avito_id,
                        account_id=account.id)

    if marked_sold > 0:
        await db.commit()

    return {"checked": len(products), "marked_sold": marked_sold}


async def check_all_accounts_sold(db: AsyncSession) -> list[dict]:
    """Run sold detection for all accounts with credentials."""
    result = await db.execute(
        select(Account).where(
            Account.client_id.isnot(None),
            Account.client_secret.isnot(None),
        )
    )
    accounts = result.scalars().all()

    summaries = []
    for account in accounts:
        summary = await check_and_mark_sold(db, account)
        summary["account_id"] = account.id
        summary["account_name"] = account.name
        summaries.append(summary)

    return summaries
