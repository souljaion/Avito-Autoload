import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

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
    sched = start_scheduler()
    yield
    sched.shutdown(wait=False)


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

    status = "ok" if db_status == "ok" else "degraded"
    code = 200 if status == "ok" else 503

    return JSONResponse(
        {"status": status, "db": db_status, "uptime_seconds": uptime},
        status_code=code,
    )
