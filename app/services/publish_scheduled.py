import structlog
from lxml import etree
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import utc_now
from app.models.account import Account
from app.models.account_description_template import AccountDescriptionTemplate
from app.models.listing import Listing
from app.models.product import Product
from app.services.avito_client import AvitoClient
from app.services.feed_generator import build_ad_element, is_ready_for_feed

logger = structlog.get_logger(__name__)


async def publish_scheduled_products(db: AsyncSession) -> dict:
    """Find scheduled listings whose time has come and publish them."""
    now = utc_now()

    result = await db.execute(
        select(Listing)
        .options(
            selectinload(Listing.product).selectinload(Product.images),
            selectinload(Listing.account),
            selectinload(Listing.images),
        )
        .where(Listing.status == "scheduled", Listing.scheduled_at <= now)
        .order_by(Listing.scheduled_at)
    )
    listings = result.scalars().all()

    if not listings:
        return {"published": 0, "skipped": 0, "errors": 0}

    published = 0
    skipped = 0
    errors = 0

    # Group by account
    by_account: dict[int, list[Listing]] = {}
    for ls in listings:
        by_account.setdefault(ls.account_id, []).append(ls)

    for acc_id, acc_listings in by_account.items():
        account = await db.get(Account, acc_id)
        if not account:
            skipped += len(acc_listings)
            continue

        # Load account description template
        tmpl_result = await db.execute(
            select(AccountDescriptionTemplate).where(
                AccountDescriptionTemplate.account_id == acc_id
            )
        )
        tmpl = tmpl_result.scalar_one_or_none()
        account_description = tmpl.description_template if tmpl else None
        has_template = bool(account_description)

        ready = []
        for ls in acc_listings:
            if not ls.product or not is_ready_for_feed(ls.product, has_account_template=has_template):
                logger.warning("Scheduled listing %d product not ready, skipping", ls.id)
                skipped += 1
                continue
            ready.append(ls)

        if not ready:
            continue

        from app.config import settings
        base_url = settings.BASE_URL
        root = etree.Element("Ads", formatVersion="3", target="Avito.ru")
        for ls in ready:
            # Resolve effective description
            effective_desc = ls.product.description
            if not ls.product.use_custom_description and account_description:
                effective_desc = account_description
            ad = build_ad_element(ls.product, account, base_url, description_override=effective_desc)
            root.append(ad)

        xml_bytes = etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)

        client = AvitoClient(account, db)
        try:
            await client.upload_feed(xml_bytes, f"scheduled_{acc_id}.xml")
            for ls in ready:
                ls.status = "published"
                ls.published_at = now
                ls.product.status = "active"
                ls.product.published_at = now
                ls.product.scheduled_at = None
                published += 1
            await db.commit()
            logger.info("Published %d listings for account %s", len(ready), account.name)
        except Exception as e:
            logger.error("Publish failed for account %s: %s", account.name, e)
            errors += len(ready)
        finally:
            await client.close()

    return {"published": published, "skipped": skipped, "errors": errors}
