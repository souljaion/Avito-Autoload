"""Sync existing autoload ads from Avito into the products table."""

from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.product import Product
from app.services.avito_client import AvitoClient

logger = structlog.get_logger(__name__)


async def sync_ads_from_avito(
    account_id: int, db: AsyncSession, client: AvitoClient | None = None,
) -> dict:
    """Sync applied ads from the latest Avito autoload report into products.

    Returns {"synced": N, "created": N, "skipped": N, "error": str|None}.
    """
    account = await db.get(Account, account_id)
    if not account:
        return {"synced": 0, "created": 0, "skipped": 0, "error": "Account not found"}

    own_client = client is None
    if own_client:
        client = AvitoClient(account, db)

    try:
        # Get latest report
        reports_data = await client.get_reports()
        reports = reports_data.get("reports") or []
        if not reports:
            return {"synced": 0, "created": 0, "skipped": 0, "error": "No reports found"}

        report_id = reports[0].get("id")
        if not report_id:
            return {"synced": 0, "created": 0, "skipped": 0, "error": "Report has no id"}

        # Fetch all items from report
        items = await client.get_report_items_all(report_id)

        # Get existing products for this account by avito_id
        existing_result = await db.execute(
            select(Product).where(
                Product.account_id == account_id,
                Product.avito_id.isnot(None),
            )
        )
        existing_by_avito_id = {p.avito_id: p for p in existing_result.scalars().all()}

        # Also get products by sku (ad_id) for matching
        sku_result = await db.execute(
            select(Product).where(
                Product.account_id == account_id,
                Product.sku.isnot(None),
            )
        )
        existing_by_sku = {p.sku: p for p in sku_result.scalars().all()}

        # All avito_ids across all accounts to avoid dupes
        all_avito_result = await db.execute(
            select(Product.avito_id).where(Product.avito_id.isnot(None))
        )
        all_avito_ids = {row[0] for row in all_avito_result.all()}

        created = 0
        synced = 0
        skipped = 0

        for item in items:
            try:
                status = item.get("status", "")
                if status != "applied":
                    skipped += 1
                    continue

                avito_id = item.get("avito_id")
                ad_id = str(item.get("ad_id", "")) or None

                if not avito_id:
                    skipped += 1
                    continue

                avito_id = int(avito_id)

                # Check if already exists by avito_id
                if avito_id in existing_by_avito_id:
                    synced += 1
                    continue

                # Check if exists by sku (ad_id) and fill avito_id
                if ad_id and ad_id in existing_by_sku:
                    product = existing_by_sku[ad_id]
                    if product.avito_id is None and avito_id not in all_avito_ids:
                        product.avito_id = avito_id
                        all_avito_ids.add(avito_id)
                        synced += 1
                    else:
                        skipped += 1
                    continue

                # Skip if avito_id exists on another account
                if avito_id in all_avito_ids:
                    skipped += 1
                    continue

                # Create new product
                product = Product(
                    avito_id=avito_id,
                    sku=ad_id,
                    account_id=account_id,
                    status="imported",
                    title=f"[Авито] {avito_id}",
                    published_at=datetime.now(timezone.utc).replace(tzinfo=None),
                )
                db.add(product)
                all_avito_ids.add(avito_id)
                existing_by_avito_id[avito_id] = product
                created += 1

            except Exception as e:
                logger.warning("autoload_sync.item_error", avito_id=item.get("avito_id"), error=str(e))
                skipped += 1

        await db.commit()
        logger.info(
            "autoload_sync.done",
            account=account.name,
            account_id=account_id,
            report_id=report_id,
            created=created,
            synced=synced,
            skipped=skipped,
            total_items=len(items),
        )
        return {"synced": synced, "created": created, "skipped": skipped, "error": None}

    except Exception as e:
        await db.rollback()
        logger.exception("autoload_sync.failed", account_id=account_id, error=str(e))
        return {"synced": 0, "created": 0, "skipped": 0, "error": str(e)}
    finally:
        if own_client:
            await client.close()
