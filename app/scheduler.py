import asyncio
from datetime import datetime

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.db import async_session
from app.services.avito_client import refresh_all_tokens
from app.services.avito_import import import_all_accounts
from app.services.image_sync import sync_images_from_crm
from app.services.publish_scheduled import publish_scheduled_products
from app.services.sold_detection import check_all_accounts_sold
from app.services.stats_sync import sync_all_stats

logger = structlog.get_logger(__name__)

RETRY_DELAY = 300  # 5 minutes
MAX_RETRIES = 2

_job_last_success: dict[str, datetime] = {}


def _record_job_success(job_name: str) -> None:
    _job_last_success[job_name] = datetime.utcnow()


def get_job_health() -> dict[str, str]:
    """Return last success times as ISO strings for the /health endpoint."""
    return {k: v.isoformat() for k, v in _job_last_success.items()}


async def _run_with_retry(name: str, coro_factory):
    """Run an async job with retry on failure.

    Returns the coroutine result on success, or False if all retries exhausted.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        async with async_session() as db:
            try:
                result = await coro_factory(db)
                return result if result is not None else True
            except Exception:
                logger.exception("Job '%s' failed (attempt %d/%d)", name, attempt, MAX_RETRIES)
                if attempt < MAX_RETRIES:
                    logger.info("Retrying '%s' in %ds...", name, RETRY_DELAY)
                    await asyncio.sleep(RETRY_DELAY)
    logger.error("Job '%s' exhausted all %d retries", name, MAX_RETRIES)
    return False


async def _job_sync_stats():
    """Background job: sync stats for all accounts."""
    async def run(db):
        results = await sync_all_stats(db)
        for r in results:
            if "error" in r:
                logger.error("Stats sync error for %s: %s", r["account"], r["error"])
            else:
                logger.info("Stats sync: %s — %d/%d", r["account"], r["synced"], r["total"])
    if await _run_with_retry("stats_sync", run) is not False:
        _record_job_success("stats_sync")


async def _job_publish_scheduled():
    """Background job: publish scheduled products."""
    async def run(db):
        result = await publish_scheduled_products(db)
        if result["published"] or result["errors"]:
            logger.info(
                "Publish scheduled: %d published, %d skipped, %d errors",
                result["published"], result["skipped"], result["errors"],
            )
    if await _run_with_retry("publish_scheduled", run) is not False:
        _record_job_success("publish_scheduled")


async def _job_sync_images():
    """Background job: sync images from CRM for products without photos."""
    async def run(db):
        result = await sync_images_from_crm(db)
        if result["synced"]:
            logger.info("image_sync: synced=%d, skipped=%d", result["synced"], result["already_had"])
    if await _run_with_retry("image_sync", run) is not False:
        _record_job_success("image_sync")


async def _job_check_sold():
    """Background job: detect sold items on Avito."""
    async def run(db):
        results = await check_all_accounts_sold(db)
        for r in results:
            if r.get("marked_sold"):
                logger.info("Sold detection: %s — %d marked sold",
                            r["account_name"], r["marked_sold"])
    if await _run_with_retry("sold_detection", run) is not False:
        _record_job_success("sold_detection")


async def _job_import_items():
    """Background job: import new items from Avito."""
    async def run(db):
        results = await import_all_accounts(db)
        for r in results:
            if "error" in r:
                logger.error("avito_import.error", account=r["account"], error=r["error"])
            else:
                logger.info(
                    "avito_import.done",
                    account=r["account"],
                    imported=r["imported"],
                    marked_removed=r.get("marked_removed", 0),
                    total=r["total"],
                )
    if await _run_with_retry("avito_import", run) is not False:
        _record_job_success("avito_import")


async def _job_cleanup_removed():
    """Background job: physically delete products removed > 48h ago."""
    async def run(db):
        import os
        import shutil
        from datetime import datetime, timedelta
        from sqlalchemy import select
        from app.config import settings
        from app.models.product import Product

        cutoff = datetime.utcnow() - timedelta(hours=48)
        result = await db.execute(
            select(Product).where(Product.status == "removed", Product.removed_at < cutoff)
        )
        products = result.scalars().all()
        if not products:
            return
        for p in products:
            product_dir = os.path.join(settings.MEDIA_DIR, "products", str(p.id))
            if os.path.isdir(product_dir):
                shutil.rmtree(product_dir, ignore_errors=True)
            await db.delete(p)
        await db.commit()
        logger.info("Cleanup: physically deleted %d removed products", len(products))
    if await _run_with_retry("cleanup_removed", run) is not False:
        _record_job_success("cleanup_removed")


async def _job_auto_generate_feeds():
    """Background job: generate feeds for accounts based on avito_sync_minute."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    from sqlalchemy import select, func
    from app.models.account import Account
    from app.models.feed_export import FeedExport
    from app.services.feed_generator import generate_feed

    try:
        MSK = ZoneInfo("Europe/Moscow")
        now_msk = datetime.now(MSK)
        current_minute = now_msk.minute

        async with async_session() as db:
            accs = await db.execute(
                select(Account).where(
                    Account.autoload_enabled == True,
                    Account.avito_sync_minute.isnot(None),
                )
            )
            accounts = accs.scalars().all()

            for acc in accounts:
                # Generate 5 minutes before sync time
                target_minute = (acc.avito_sync_minute - 5) % 60
                if current_minute != target_minute:
                    continue

                # Dedup: skip if feed was generated within last 50 minutes
                recent = await db.execute(
                    select(func.count()).select_from(FeedExport).where(
                        FeedExport.account_id == acc.id,
                        FeedExport.created_at >= datetime.utcnow() - timedelta(minutes=50),
                    )
                )
                if (recent.scalar() or 0) > 0:
                    continue

                try:
                    filepath, count = await generate_feed(acc.id, db)
                    logger.info("Auto feed: %s — %d products, %s", acc.name, count, filepath)
                except Exception:
                    logger.exception("Auto feed failed for %s", acc.name)

        _record_job_success("auto_generate_feeds")
    except Exception:
        logger.exception("auto_generate_feeds.fatal")


async def _job_auto_generate_feeds_fallback():
    """Background job: hourly feed generation for accounts without sync_minute."""
    from datetime import datetime, timedelta
    from sqlalchemy import select, func
    from app.models.account import Account
    from app.models.feed_export import FeedExport
    from app.services.feed_generator import generate_feed

    try:
        async with async_session() as db:
            accs = await db.execute(
                select(Account).where(
                    Account.autoload_enabled == True,
                    Account.avito_sync_minute.is_(None),
                )
            )
            accounts = accs.scalars().all()

            for acc in accounts:
                # Dedup: skip if feed was generated within last 50 minutes
                recent = await db.execute(
                    select(func.count()).select_from(FeedExport).where(
                        FeedExport.account_id == acc.id,
                        FeedExport.created_at >= datetime.utcnow() - timedelta(minutes=50),
                    )
                )
                if (recent.scalar() or 0) > 0:
                    continue

                try:
                    filepath, count = await generate_feed(acc.id, db)
                    logger.info("Auto feed (fallback): %s — %d products", acc.name, count)
                except Exception:
                    logger.exception("Auto feed fallback failed for %s", acc.name)

        _record_job_success("auto_generate_feeds_fallback")
    except Exception:
        logger.exception("auto_generate_feeds_fallback.fatal")


async def _job_check_declined_ads():
    """Background job: check for blocked/rejected/removed ads on Avito."""
    from datetime import datetime
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from app.models.account import Account
    from app.models.product import Product
    from app.services.avito_client import AvitoClient
    from app.services.telegram_notify import send_message
    from app.db import safe_update_status

    try:
        async with async_session() as db:
            # Fetch products grouped by account
            result = await db.execute(
                select(Product)
                .options(selectinload(Product.account))
                .where(
                    Product.status.in_(["active", "published", "imported"]),
                    Product.account_id.isnot(None),
                )
            )
            products = result.scalars().all()

            # Group by account_id
            by_account: dict[int, list[Product]] = {}
            for p in products:
                by_account.setdefault(p.account_id, []).append(p)

            for account_id, account_products in by_account.items():
                account = account_products[0].account
                if not account or not account.client_id or not account.client_secret:
                    continue

                ad_ids = [str(p.id) for p in account_products]
                product_map = {str(p.id): p for p in account_products}

                client = AvitoClient(account, db)
                try:
                    items_info = await client.get_items_info(ad_ids)
                except Exception:
                    logger.exception("check_declined: failed for account %s", account.name)
                    continue
                finally:
                    await client.close()

                blocked = removed = restored = 0

                for item in items_info:
                    ad_id = str(item.get("ad_id", ""))
                    avito_status = item.get("avito_status", "")
                    product = product_map.get(ad_id)
                    if not product:
                        continue

                    if avito_status in ("blocked", "rejected"):
                        extra = dict(product.extra) if product.extra else {}
                        extra["avito_messages"] = item.get("messages") or []
                        success = await safe_update_status(
                            db, product.id, "paused", product.version,
                            extra_fields={"extra": extra},
                        )
                        if not success:
                            logger.warning("check_declined.skipped_conflict", product_id=product.id)
                            continue
                        product.version += 1
                        blocked += 1

                        # Telegram notification
                        messages = item.get("messages") or []
                        reason = messages[0].get("title", "Нет причины") if messages else "Нет причины"
                        await send_message(
                            f"🚫 Ad blocked: {product.title}\n"
                            f"Account: {account.name}\n"
                            f"Reason: {reason}\n"
                            f"Avito ID: {product.avito_id}"
                        )

                    elif avito_status == "removed":
                        if product.status != "removed" and product.removed_at is None:
                            success = await safe_update_status(
                                db, product.id, "removed", product.version,
                                extra_fields={"removed_at": datetime.utcnow()},
                            )
                            if not success:
                                logger.warning("check_declined.skipped_conflict", product_id=product.id)
                                continue
                            product.version += 1
                            removed += 1
                            logger.info("check_declined.removed", product_id=product.id, avito_id=product.avito_id)

                    elif avito_status == "active" and product.status == "paused":
                        extra = dict(product.extra) if product.extra else {}
                        if "avito_messages" in extra:
                            del extra["avito_messages"]
                        success = await safe_update_status(
                            db, product.id, "active", product.version,
                            extra_fields={"extra": extra if extra else None},
                        )
                        if not success:
                            logger.warning("check_declined.skipped_conflict", product_id=product.id)
                            continue
                        product.version += 1
                        restored += 1
                        logger.info("check_declined.restored", product_id=product.id, avito_id=product.avito_id)

                await db.commit()
                logger.info(
                    "check_declined.done",
                    account=account.name,
                    checked=len(account_products),
                    blocked=blocked,
                    removed=removed,
                    restored=restored,
                )

        _record_job_success("check_declined_ads")
    except Exception:
        logger.exception("check_declined_ads.fatal")


scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
scheduler.add_job(
    _job_sync_stats,
    "interval",
    hours=3,
    id="stats_sync",
    max_instances=1,
)
scheduler.add_job(
    _job_publish_scheduled,
    "interval",
    minutes=5,
    id="publish_scheduled",
    max_instances=1,
)
scheduler.add_job(
    _job_sync_images,
    "interval",
    minutes=30,
    id="image_sync",
    max_instances=1,
)


scheduler.add_job(
    _job_check_sold,
    "interval",
    hours=6,
    id="sold_detection",
    max_instances=1,
)
scheduler.add_job(
    _job_import_items,
    "interval",
    hours=3,
    id="avito_import",
    max_instances=1,
)


async def _job_refresh_tokens():
    """Background job: refresh OAuth tokens for all accounts."""
    async def run(db):
        return await refresh_all_tokens(db)
    if await _run_with_retry("token_refresh", run) is not False:
        _record_job_success("token_refresh")


scheduler.add_job(
    _job_refresh_tokens,
    "interval",
    minutes=50,
    id="token_refresh",
    max_instances=1,
)


scheduler.add_job(
    _job_cleanup_removed,
    "interval",
    hours=24,
    id="cleanup_removed",
    max_instances=1,
)
scheduler.add_job(
    _job_auto_generate_feeds,
    "interval",
    minutes=1,
    id="auto_generate_feeds",
    max_instances=1,
)
scheduler.add_job(
    _job_auto_generate_feeds_fallback,
    "interval",
    hours=1,
    id="auto_generate_feeds_fallback",
    max_instances=1,
)


scheduler.add_job(
    _job_check_declined_ads,
    "interval",
    hours=6,
    id="check_declined_ads",
    max_instances=1,
)


async def _job_sync_autoload_ads():
    """Background job: sync applied ads from autoload reports."""
    async def run(db):
        from sqlalchemy import select as sa_select
        from app.models.account import Account as Acc
        from app.services.autoload_sync import sync_ads_from_avito

        result = await db.execute(
            sa_select(Acc).where(Acc.autoload_enabled == True, Acc.client_id.isnot(None))
        )
        accounts = result.scalars().all()
        total_created = 0
        total_synced = 0
        for acc in accounts:
            r = await sync_ads_from_avito(acc.id, db)
            if r.get("error"):
                logger.error("autoload_sync error for %s: %s", acc.name, r["error"])
            else:
                total_created += r["created"]
                total_synced += r["synced"]
        return {"created": total_created, "synced": total_synced}

    if await _run_with_retry("sync_autoload_ads", run) is not False:
        _record_job_success("sync_autoload_ads")


scheduler.add_job(
    _job_sync_autoload_ads,
    "interval",
    hours=6,
    id="sync_autoload_ads",
    max_instances=1,
)


def start_scheduler() -> AsyncIOScheduler:
    scheduler.start()
    logger.info("Scheduler started: stats 3h, publish 5m, images 30m, sold 6h, tokens 50m, import 3h, cleanup 24h, declined 6h, autoload_sync 6h")
    return scheduler
