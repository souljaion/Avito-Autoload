"""Tests for GET /health endpoint."""

import pytest
import pytest_asyncio


@pytest.mark.asyncio
async def test_health_returns_200(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["db"] == "ok"
    assert "uptime_seconds" in data


@pytest.mark.asyncio
async def test_health_no_auth_required(client):
    """Health endpoint should work without authentication."""
    # Make a request without auth headers
    import httpx
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8001", timeout=10.0) as c:
        resp = await c.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
