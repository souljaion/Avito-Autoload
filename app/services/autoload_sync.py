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
        return {
            "synced": 0, "created": 0, "skipped": 0,
            "pass3_matched": 0, "pass3_created": 0,
            "error": "Account not found",
        }

    own_client = client is None
    if own_client:
        client = AvitoClient(account, db)

    try:
        # Get latest report
        reports_data = await client.get_reports()
        reports = reports_data.get("reports") or []
        if not reports:
            return {
                "synced": 0, "created": 0, "skipped": 0,
                "pass3_matched": 0, "pass3_created": 0,
                "error": "No reports found",
            }

        report_id = reports[0].get("id")
        if not report_id:
            return {
                "synced": 0, "created": 0, "skipped": 0,
                "pass3_matched": 0, "pass3_created": 0,
                "error": "Report has no id",
            }

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

        # ── Pass 2: Items API — fill avito_id for products with NULL ──
        avito_ids_filled = 0
        api_items: list[dict] = []
        try:
            api_items = await client.get_all_items()
            if api_items:
                # Load products with NULL avito_id for this account
                null_avito_result = await db.execute(
                    select(Product).where(
                        Product.account_id == account_id,
                        Product.avito_id.is_(None),
                    )
                )
                null_avito_products = null_avito_result.scalars().all()
                # Index by exact title for O(1) lookup
                by_title: dict[str, Product] = {}
                for p in null_avito_products:
                    if p.title and p.title not in by_title:
                        by_title[p.title] = p

                for api_item in api_items:
                    avito_id = api_item.get("id")
                    title = api_item.get("title", "")
                    if not avito_id or not title:
                        continue
                    avito_id = int(avito_id)
                    # Skip if this avito_id is already used
                    if avito_id in all_avito_ids:
                        continue
                    # Exact title match only
                    product = by_title.get(title)
                    if product and product.avito_id is None:
                        product.avito_id = avito_id
                        all_avito_ids.add(avito_id)
                        # Remove from index so we don't match again
                        del by_title[title]
                        avito_ids_filled += 1

                if avito_ids_filled:
                    await db.commit()
        except Exception as e:
            logger.warning("autoload_sync.pass2_failed", account_id=account_id, error=str(e))

        # ── Pass 3: Items API — match-then-create for ads not in DB ──
        # For each Avito ad whose avito_id we don't have:
        #   1. Try fuzzy title match against existing imported products with NULL avito_id
        #      → fill avito_id (pass3_matched)
        #   2. Otherwise create a new imported product (pass3_created)
        pass3_matched = 0
        pass3_created = 0
        try:
            if api_items:
                # Snapshot per-account avito_ids (after Pass 1+2)
                acc_avito_result = await db.execute(
                    select(Product.avito_id).where(
                        Product.account_id == account_id,
                        Product.avito_id.isnot(None),
                    )
                )
                acc_avito_ids = {row[0] for row in acc_avito_result.all()}

                # Reload NULL-avito_id products for this account (Pass 2 may have
                # consumed some; fresh read is cheap and avoids stale state).
                null_avito_result_p3 = await db.execute(
                    select(Product).where(
                        Product.account_id == account_id,
                        Product.avito_id.is_(None),
                    )
                )
                null_avito_products_p3 = list(null_avito_result_p3.scalars().all())

                # Build two title indexes for fuzzy matching:
                # 1) exact normalized (lowercase + collapsed whitespace)
                # 2) first 50 chars of normalized title — prefix fallback
                def _norm(s: str) -> str:
                    return " ".join((s or "").split()).lower()

                by_norm: dict[str, Product] = {}
                by_prefix: dict[str, Product] = {}
                for p in null_avito_products_p3:
                    n = _norm(p.title or "")
                    if not n:
                        continue
                    by_norm.setdefault(n, p)
                    by_prefix.setdefault(n[:50], p)

                def _claim(product: Product, avito_id: int) -> None:
                    """Drop product from both indexes once its avito_id is filled."""
                    n = _norm(product.title or "")
                    by_norm.pop(n, None)
                    by_prefix.pop(n[:50], None)

                now = datetime.now(timezone.utc).replace(tzinfo=None)

                for api_item in api_items:
                    raw_id = api_item.get("id")
                    if not raw_id:
                        continue
                    try:
                        avito_id = int(raw_id)
                    except (TypeError, ValueError):
                        continue
                    if avito_id in acc_avito_ids:
                        continue
                    # Avoid global avito_id collisions (another account holds it)
                    if avito_id in all_avito_ids:
                        continue

                    raw_title = api_item.get("title") or ""
                    norm_title = _norm(raw_title)

                    # Step 1 — fuzzy title match
                    matched: Product | None = None
                    if norm_title:
                        matched = by_norm.get(norm_title)
                        if matched is None:
                            matched = by_prefix.get(norm_title[:50])

                    if matched is not None:
                        matched.avito_id = avito_id
                        all_avito_ids.add(avito_id)
                        acc_avito_ids.add(avito_id)
                        _claim(matched, avito_id)
                        pass3_matched += 1
                        logger.info(
                            "autoload_sync.pass3_matched",
                            account_id=account_id,
                            avito_id=avito_id,
                            product_id=matched.id,
                            title=raw_title[:80],
                        )
                        continue

                    # Step 2 — create new imported product
                    title = raw_title or f"[Авито] {avito_id}"
                    price = api_item.get("price")
                    try:
                        price_val = int(price) if price is not None else None
                    except (TypeError, ValueError):
                        price_val = None

                    product = Product(
                        avito_id=avito_id,
                        account_id=account_id,
                        title=title[:255],
                        price=price_val,
                        status="imported",
                        published_at=now,
                    )
                    db.add(product)
                    all_avito_ids.add(avito_id)
                    acc_avito_ids.add(avito_id)
                    pass3_created += 1
                    logger.info(
                        "autoload_sync.pass3_created",
                        account_id=account_id,
                        avito_id=avito_id,
                        title=title[:80],
                    )

                if pass3_matched or pass3_created:
                    await db.commit()
        except Exception as e:
            await db.rollback()
            logger.warning("autoload_sync.pass3_failed", account_id=account_id, error=str(e))

        logger.info(
            "autoload_sync.done",
            account=account.name,
            account_id=account_id,
            report_id=report_id,
            created=created,
            synced=synced,
            skipped=skipped,
            avito_ids_filled=avito_ids_filled,
            pass3_matched=pass3_matched,
            pass3_created=pass3_created,
            total_items=len(items),
        )
        return {
            "synced": synced, "created": created, "skipped": skipped,
            "avito_ids_filled": avito_ids_filled,
            "pass3_matched": pass3_matched,
            "pass3_created": pass3_created,
            "error": None,
        }

    except Exception as e:
        await db.rollback()
        logger.exception("autoload_sync.failed", account_id=account_id, error=str(e))
        return {
            "synced": 0, "created": 0, "skipped": 0,
            "pass3_matched": 0, "pass3_created": 0,
            "error": str(e),
        }
    finally:
        if own_client:
            await client.close()
