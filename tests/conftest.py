"""
Shared fixtures for tests.

Integration tests run against the live server on localhost:8001.
Unit tests (feed_generator, avito_client) use mocks and don't need DB/server.
"""

from base64 import b64encode

import pytest
import pytest_asyncio
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import engine


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
