"""
Shared fixtures for tests.

Integration tests run against the live server on localhost:8001.
Unit tests (feed_generator, avito_client) use mocks and don't need DB/server.

HARD GUARD: This module refuses to let pytest run against a production
database. The check runs at import time (before any test is collected).
To create the test DB:
    createdb -U avito_user -h localhost -p 5433 avito_autoload_test
    DATABASE_URL=postgresql+asyncpg://avito_user:avito_pass@localhost:5433/avito_autoload_test \
        alembic upgrade head
"""

import os
from base64 import b64encode

import pytest
import pytest_asyncio
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import engine

# ---------------------------------------------------------------------------
# HARD GUARD — runs at import time, before any test is collected
# ---------------------------------------------------------------------------
_PRODUCTION_URL = (
    "postgresql+asyncpg://avito_user:avito_pass@localhost:5433/avito_autoload"
)

_db_url = str(settings.DATABASE_URL)

# Belt: exact match against known production URL
if _db_url.rstrip("/") == _PRODUCTION_URL:
    raise RuntimeError(
        f"REFUSING to run tests against the PRODUCTION database: {_db_url}\n"
        f"Set DATABASE_URL to a test DB (e.g. avito_autoload_test) "
        f"or export TESTING=1."
    )

# Suspenders: URL must contain 'test' OR TESTING=1 must be set
_has_test_in_url = "test" in _db_url.lower()
_testing_env = os.environ.get("TESTING", "") == "1"

if not _has_test_in_url and not _testing_env:
    raise RuntimeError(
        f"REFUSING to run tests against non-test database: {_db_url}\n"
        f"Set DATABASE_URL to a test DB (must contain 'test' in the name) "
        f"or export TESTING=1."
    )
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db() -> AsyncSession:
    """Provide a transactional DB session that rolls back after each test."""
    async with engine.connect() as conn:
        trans = await conn.begin()
        session = AsyncSession(bind=conn, expire_on_commit=False)
        yield session
        await session.close()
        await trans.rollback()


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """HTTP Basic Auth headers for test requests."""
    creds = b64encode(
        f"{settings.BASIC_AUTH_USER}:{settings.BASIC_AUTH_PASSWORD}".encode()
    ).decode()
    return {"Authorization": f"Basic {creds}"}


@pytest_asyncio.fixture
async def client(auth_headers):
    """httpx AsyncClient pointing at the live local server."""
    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:8001",
        headers=auth_headers,
        timeout=10.0,
    ) as c:
        yield c


@pytest_asyncio.fixture(autouse=True)
async def _clear_in_memory_cache():
    """Reset the in-memory TTL cache between tests to avoid cross-test pollution."""
    from app.cache import cache
    await cache.clear()
    yield
    await cache.clear()


@pytest_asyncio.fixture
async def isolated_db():
    """Isolated DB session for integration tests where the endpoint calls db.commit().

    The standard `db` fixture wraps everything in a transaction and rolls back.
    But if the code under test calls commit(), it finalizes that transaction and
    breaks subsequent tests. This fixture creates its own engine+connection so
    the pool isn't polluted.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    eng = create_async_engine(str(settings.DATABASE_URL))
    async with eng.connect() as conn:
        trans = await conn.begin()
        session = AsyncSession(bind=conn, expire_on_commit=False)
        yield session
        await session.close()
        if trans.is_active:
            await trans.rollback()
    await eng.dispose()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _seed_test_account():
    """Ensure account id=1 exists for integration tests that reference it."""
    import uuid
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy import text

    e = create_async_engine(str(settings.DATABASE_URL))
    async with e.begin() as conn:
        row = await conn.execute(text("SELECT id FROM accounts WHERE id = 1"))
        if not row.scalar():
            await conn.execute(text(
                "INSERT INTO accounts (id, name, client_id, client_secret, feed_token, created_at, updated_at) "
                "VALUES (1, 'TestAccount', 'test_client_id', 'test_secret', :token, now(), now()) "
                "ON CONFLICT (id) DO NOTHING"
            ), {"token": str(uuid.uuid4())})
    await e.dispose()
