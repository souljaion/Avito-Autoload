"""Tests for products API endpoints (integration tests against running server)."""

import pytest
import pytest_asyncio


@pytest.mark.asyncio
async def test_products_list_returns_200(client):
    resp = await client.get("/products")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_products_list_requires_auth():
    """Products page should require authentication."""
    import httpx
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8001", timeout=10.0) as c:
        resp = await c.get("/products")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_product(client):
    resp = await client.post(
        "/products/new",
        data={
            "title": "Test Product Pytest",
            "price": "1500",
            "status": "draft",
        },
        follow_redirects=False,
    )
    # Should redirect to product detail on success
    assert resp.status_code == 303
    location = resp.headers.get("location", "")
    assert "/products/" in location


@pytest.mark.asyncio
async def test_patch_product_status(client):
    """Create a product via API, then PATCH its status."""
    # Create product first
    create_resp = await client.post(
        "/products/new",
        data={"title": "Patch Status Test", "price": "2000", "status": "draft"},
        follow_redirects=False,
    )
    assert create_resp.status_code == 303
    location = create_resp.headers["location"]
    # Extract product ID from redirect URL like /products/123
    pid = location.rstrip("/").split("/")[-1]

    resp = await client.patch(
        f"/products/{pid}",
        json={"status": "active"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["status"] == "active"


@pytest.mark.asyncio
async def test_patch_product_price(client):
    create_resp = await client.post(
        "/products/new",
        data={"title": "Patch Price Test", "price": "1000", "status": "draft"},
        follow_redirects=False,
    )
    assert create_resp.status_code == 303
    pid = create_resp.headers["location"].rstrip("/").split("/")[-1]

    resp = await client.patch(
        f"/products/{pid}",
        json={"price": 2500},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["price"] == 2500


@pytest.mark.asyncio
async def test_patch_nonexistent_product(client):
    resp = await client.patch(
        "/products/999999",
        json={"status": "active"},
    )
    assert resp.status_code == 404
