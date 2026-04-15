import structlog
import asyncpg
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.product import Product

logger = structlog.get_logger(__name__)

CRM_QUERY = """
SELECT DISTINCT ON (item_id)
    item_id,
    raw_json->'context'->'value'->'images'->'main'->>'140x105' AS image_url
FROM chats
WHERE item_id IS NOT NULL
AND raw_json->'context'->'value'->'images'->'main'->>'140x105' IS NOT NULL
ORDER BY item_id, id DESC;
"""


async def sync_images_from_crm(db: AsyncSession) -> dict:
    """Fetch image URLs from CRM chats and save to products.image_url."""
    if not settings.CRM_DSN or settings.CRM_DSN.strip() == "":
        logger.info("image_sync.skipped", reason="CRM_DSN not configured")
        return {"synced": 0, "not_found": 0, "already_had": 0, "total_crm": 0}

    # Connect to CRM DB
    crm_conn = await asyncpg.connect(settings.CRM_DSN)
    try:
        rows = await crm_conn.fetch(CRM_QUERY)
    finally:
        await crm_conn.close()

    crm_map: dict[int, str] = {row["item_id"]: row["image_url"] for row in rows}
    logger.info("CRM returned %d items with images", len(crm_map))

    # Get all products with avito_id
    result = await db.execute(
        select(Product.id, Product.avito_id, Product.image_url)
        .where(Product.avito_id.isnot(None))
    )
    products = result.all()

    synced = 0
    not_found = 0
    already_had = 0

    for pid, avito_id, existing_url in products:
        crm_url = crm_map.get(avito_id)
        if not crm_url:
            not_found += 1
            continue
        if existing_url:
            already_had += 1
            continue

        await db.execute(
            update(Product).where(Product.id == pid).values(image_url=crm_url)
        )
        synced += 1

    await db.commit()
    logger.info("Image sync: %d synced, %d not found, %d already had", synced, not_found, already_had)

    return {
        "synced": synced,
        "not_found": not_found,
        "already_had": already_had,
        "total_crm": len(crm_map),
    }
