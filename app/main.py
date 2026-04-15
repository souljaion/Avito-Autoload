import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

import structlog

from app.config import settings
from app.logging_config import setup_logging
from app.middleware.auth import BasicAuthMiddleware
from app.scheduler import start_scheduler
from app.routes.dashboard import router as dashboard_router
from app.routes.accounts import router as accounts_router
from app.routes.products import router as products_router
from app.routes.images import router as images_router
from app.routes.feeds import router as feeds_router
from app.routes.autoload import router as autoload_router
from app.routes.reports import router as reports_router
from app.routes.categories import router as categories_router
from app.routes.analytics import router as analytics_router
from app.routes.schedule import router as schedule_router
from app.routes.listings import router as listings_router
from app.routes.models import router as models_router
from app.routes.photo_packs import router as photo_packs_router

_start_time = time.monotonic()


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    if settings.SENTRY_DSN:
        import sentry_sdk
        sentry_sdk.init(dsn=settings.SENTRY_DSN, traces_sample_rate=0.1)

    # Only start scheduler in one worker to avoid duplicate jobs
    import fcntl
    lock_path = "/tmp/avito-autoload-scheduler.lock"
    sched = None
    lock_file = None
    try:
        lock_file = open(lock_path, "w")
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        sched = start_scheduler()
        app.state.scheduler = sched
    except (IOError, OSError):
        pass  # Another worker already holds the lock

    # Zulla diagnostics
    try:
        from app.db import async_session as _async_session
        async with _async_session() as _db:
            rows = (await _db.execute(text(
                "SELECT p.status, COUNT(*) FROM products p "
                "JOIN accounts a ON a.id = p.account_id "
                "WHERE a.name = 'Zulla' GROUP BY p.status ORDER BY p.status"
            ))).all()
            diag_log = structlog.get_logger("zulla_diag")
            for status, cnt in rows:
                diag_log.info("zulla_products", status=status, count=cnt)
    except Exception as e:
        structlog.get_logger("zulla_diag").warning("zulla_diag_failed", error=str(e))

    yield

    if sched:
        sched.shutdown(wait=False)
    if lock_file:
        lock_file.close()


app = FastAPI(title="Avito Autoload", version="0.1.0", lifespan=lifespan)
app.add_middleware(BasicAuthMiddleware)

os.makedirs("app/static", exist_ok=True)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

os.makedirs(settings.MEDIA_DIR, exist_ok=True)
app.mount("/media", StaticFiles(directory=settings.MEDIA_DIR), name="media")

app.include_router(dashboard_router)
app.include_router(accounts_router)
app.include_router(products_router)
app.include_router(images_router)
app.include_router(feeds_router)
app.include_router(autoload_router)
app.include_router(reports_router)
app.include_router(categories_router)
app.include_router(analytics_router)
app.include_router(schedule_router)
app.include_router(listings_router)
app.include_router(models_router)
app.include_router(photo_packs_router)


@app.get("/health")
async def health():
    from app.db import async_session

    uptime = round(time.monotonic() - _start_time, 1)
    db_status = "ok"

    try:
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        db_status = "error"

    # Scheduler jobs
    from app.scheduler import get_job_health
    job_health = get_job_health()
    jobs_info = {}
    sched = getattr(app.state, "scheduler", None)
    if sched:
        for job in sched.get_jobs():
            next_run = job.next_run_time
            jobs_info[job.id] = {
                "next_run": next_run.isoformat() if next_run else None,
                "status": "scheduled" if next_run else "paused",
                "last_success": job_health.get(job.id),
            }

    status = "ok" if db_status == "ok" else "degraded"

    return JSONResponse(
        {"status": status, "jobs": jobs_info, "db": db_status, "uptime_seconds": uptime},
        status_code=200,
    )
