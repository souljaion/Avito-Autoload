from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine, AsyncSession
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=3600,
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with async_session() as session:
        yield session


def utc_now() -> datetime:
    """Return current UTC time as a naive datetime (for DB storage)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def safe_update_status(
    db: AsyncSession,
    product_id: int,
    new_status: str,
    expected_version: int,
    extra_fields: dict | None = None,
) -> bool:
    """Atomically update product status only if version matches.

    Returns True if update succeeded, False if another job already modified it.
    """
    from app.models.product import Product

    values = {"status": new_status, "version": expected_version + 1}
    if extra_fields:
        values.update(extra_fields)
    result = await db.execute(
        update(Product)
        .where(Product.id == product_id)
        .where(Product.version == expected_version)
        .values(**values)
    )
    return result.rowcount == 1
