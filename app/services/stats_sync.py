import structlog
from sqlalchemy import select, cast, Date
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import utc_now
from app.models.account import Account
from app.models.item_stats import ItemStats
from app.models.product import Product
from app.services.avito_client import AvitoClient

logger = structlog.get_logger(__name__)


async def sync_stats_for_account(account: Account, db: AsyncSession) -> dict:
    """Sync item stats for one account. Returns summary dict."""
    client = AvitoClient(account, db)
    try:
        user_id = account.avito_user_id
        if not user_id:
            user_id = await client.get_user_id()
            account.avito_user_id = user_id
            await db.commit()

        result = await db.execute(
            select(Product).where(
                Product.account_id == account.id,
                Product.avito_id.isnot(None),
            )
        )
        products = result.scalars().all()
        if not products:
            return {"account": account.name, "synced": 0, "total": 0}

        avito_id_to_product = {p.avito_id: p for p in products}
        avito_ids = list(avito_id_to_product.keys())

        stats_map = await client.get_items_stats(user_id, avito_ids)

        now = utc_now()

        # Build batch of rows to upsert
        rows = []
        for avito_id, stats in stats_map.items():
            product = avito_id_to_product.get(avito_id)
            if not product:
                continue
            rows.append({
                "product_id": product.id,
                "avito_id": avito_id,
                "views": stats.get("views", 0),
                "contacts": stats.get("contacts", 0),
                "favorites": stats.get("favorites", 0),
                "price": product.price,
                "captured_at": now,
            })

        synced = len(rows)
        if rows:
            stmt = pg_insert(ItemStats).values(rows)
            stmt = stmt.on_conflict_do_update(
                index_elements=[
                    ItemStats.product_id,
                    cast(ItemStats.captured_at, Date),
                ],
                set_={
                    "views": stmt.excluded.views,
                    "contacts": stmt.excluded.contacts,
                    "favorites": stmt.excluded.favorites,
                    "price": stmt.excluded.price,
                    "captured_at": stmt.excluded.captured_at,
                },
            )
            await db.execute(stmt)

        await db.commit()
        logger.info("Stats synced for %s: %d/%d items", account.name, synced, len(avito_ids))
        return {"account": account.name, "synced": synced, "total": len(avito_ids)}

    finally:
        await client.close()


async def sync_all_stats(db: AsyncSession) -> list[dict]:
    """Sync stats for all accounts with credentials."""
    result = await db.execute(
        select(Account).where(Account.access_token.isnot(None))
    )
    accounts = result.scalars().all()

    summaries = []
    for account in accounts:
        try:
            summary = await sync_stats_for_account(account, db)
            summaries.append(summary)
        except Exception as e:
            logger.exception("Stats sync failed for account %s", account.name)
            summaries.append({"account": account.name, "error": str(e)})

    return summaries
