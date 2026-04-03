import asyncio

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.db import async_session
from app.services.image_sync import sync_images_from_crm
from app.services.publish_scheduled import publish_scheduled_products
from app.services.stats_sync import sync_all_stats

logger = structlog.get_logger(__name__)

RETRY_DELAY = 300  # 5 minutes
MAX_RETRIES = 2


async def _run_with_retry(name: str, coro_factory):
    """Run an async job with retry on failure."""
    for attempt in range(1, MAX_RETRIES + 1):
        async with async_session() as db:
            try:
                return await coro_factory(db)
            except Exception:
                logger.exception("Job '%s' failed (attempt %d/%d)", name, attempt, MAX_RETRIES)
                if attempt < MAX_RETRIES:
                    logger.info("Retrying '%s' in %ds...", name, RETRY_DELAY)
                    await asyncio.sleep(RETRY_DELAY)
    logger.error("Job '%s' exhausted all %d retries", name, MAX_RETRIES)


async def _job_sync_stats():
    """Background job: sync stats for all accounts."""
    async def run(db):
        results = await sync_all_stats(db)
        for r in results:
            if "error" in r:
                logger.error("Stats sync error for %s: %s", r["account"], r["error"])
            else:
                logger.info("Stats sync: %s — %d/%d", r["account"], r["synced"], r["total"])
    await _run_with_retry("stats_sync", run)


async def _job_publish_scheduled():
    """Background job: publish scheduled products."""
    async def run(db):
        result = await publish_scheduled_products(db)
        if result["published"] or result["errors"]:
            logger.info(
                "Publish scheduled: %d published, %d skipped, %d errors",
                result["published"], result["skipped"], result["errors"],
            )
    await _run_with_retry("publish_scheduled", run)


async def _job_sync_images():
    """Background job: sync images from CRM for products without photos."""
    async def run(db):
        result = await sync_images_from_crm(db)
        if result["synced"]:
            logger.info("image_sync: synced=%d, skipped=%d", result["synced"], result["already_had"])
    await _run_with_retry("image_sync", run)


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


def start_scheduler() -> AsyncIOScheduler:
    scheduler.start()
    logger.info("Scheduler started: stats 3h, publish 5m, images 30m")
    return scheduler
