"""Tests for image_sync service: sync_images_from_crm()."""

import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
@patch("app.services.image_sync.settings")
async def test_crm_dsn_not_configured_returns_zeros(mock_settings):
    """When CRM_DSN is empty, should return early with all-zero counts."""
    mock_settings.CRM_DSN = ""
    from app.services.image_sync import sync_images_from_crm

    db = AsyncMock()
    result = await sync_images_from_crm(db)

    assert result == {"synced": 0, "not_found": 0, "already_had": 0, "total_crm": 0}
    db.execute.assert_not_called()


@pytest.mark.asyncio
@patch("app.services.image_sync.settings")
async def test_crm_dsn_whitespace_returns_zeros(mock_settings):
    """When CRM_DSN is only whitespace, should return early."""
    mock_settings.CRM_DSN = "   "
    from app.services.image_sync import sync_images_from_crm

    db = AsyncMock()
    result = await sync_images_from_crm(db)

    assert result == {"synced": 0, "not_found": 0, "already_had": 0, "total_crm": 0}


@pytest.mark.asyncio
@patch("app.services.image_sync.asyncpg")
@patch("app.services.image_sync.settings")
async def test_no_products_with_avito_id(mock_settings, mock_asyncpg):
    """When there are no products with avito_id, synced should be 0."""
    mock_settings.CRM_DSN = "postgresql://host/db"

    # Mock CRM connection returning some rows
    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = [
        {"item_id": 100, "image_url": "https://img.avito.st/100.jpg"},
    ]
    mock_asyncpg.connect = AsyncMock(return_value=mock_conn)

    # Mock db session returning no products
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = []
    db.execute.return_value = mock_result

    from app.services.image_sync import sync_images_from_crm

    result = await sync_images_from_crm(db)

    assert result["synced"] == 0
    assert result["not_found"] == 0
    assert result["already_had"] == 0
    assert result["total_crm"] == 1
    mock_conn.close.assert_awaited_once()


@pytest.mark.asyncio
@patch("app.services.image_sync.asyncpg")
@patch("app.services.image_sync.settings")
async def test_products_matched_image_url_updated(mock_settings, mock_asyncpg):
    """Products matched by avito_id should get image_url updated."""
    mock_settings.CRM_DSN = "postgresql://host/db"

    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = [
        {"item_id": 100, "image_url": "https://img.avito.st/100.jpg"},
        {"item_id": 200, "image_url": "https://img.avito.st/200.jpg"},
    ]
    mock_asyncpg.connect = AsyncMock(return_value=mock_conn)

    # Two products: one matching avito_id=100 (no image), one matching 200 (no image)
    db = AsyncMock()
    select_result = MagicMock()
    select_result.all.return_value = [
        (1, 100, None),   # pid=1, avito_id=100, no existing image
        (2, 200, None),   # pid=2, avito_id=200, no existing image
    ]
    # First execute = select, subsequent = updates
    db.execute.return_value = select_result

    from app.services.image_sync import sync_images_from_crm

    result = await sync_images_from_crm(db)

    assert result["synced"] == 2
    assert result["not_found"] == 0
    assert result["already_had"] == 0
    assert result["total_crm"] == 2
    db.commit.assert_awaited_once()
    # 1 select + 2 update calls
    assert db.execute.await_count == 3


@pytest.mark.asyncio
@patch("app.services.image_sync.asyncpg")
@patch("app.services.image_sync.settings")
async def test_product_already_has_image_url(mock_settings, mock_asyncpg):
    """Products that already have image_url should count as already_had."""
    mock_settings.CRM_DSN = "postgresql://host/db"

    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = [
        {"item_id": 100, "image_url": "https://img.avito.st/100.jpg"},
    ]
    mock_asyncpg.connect = AsyncMock(return_value=mock_conn)

    db = AsyncMock()
    select_result = MagicMock()
    select_result.all.return_value = [
        (1, 100, "https://existing.img/photo.jpg"),  # already has image
    ]
    db.execute.return_value = select_result

    from app.services.image_sync import sync_images_from_crm

    result = await sync_images_from_crm(db)

    assert result["synced"] == 0
    assert result["already_had"] == 1
    assert result["not_found"] == 0
    # Only 1 execute call (select), no update calls
    assert db.execute.await_count == 1


@pytest.mark.asyncio
@patch("app.services.image_sync.asyncpg")
@patch("app.services.image_sync.settings")
async def test_product_not_in_crm_counts_as_not_found(mock_settings, mock_asyncpg):
    """Products whose avito_id is not in CRM data should count as not_found."""
    mock_settings.CRM_DSN = "postgresql://host/db"

    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = [
        {"item_id": 999, "image_url": "https://img.avito.st/999.jpg"},
    ]
    mock_asyncpg.connect = AsyncMock(return_value=mock_conn)

    db = AsyncMock()
    select_result = MagicMock()
    select_result.all.return_value = [
        (1, 100, None),  # avito_id=100 not in CRM data
    ]
    db.execute.return_value = select_result

    from app.services.image_sync import sync_images_from_crm

    result = await sync_images_from_crm(db)

    assert result["synced"] == 0
    assert result["not_found"] == 1
    assert result["already_had"] == 0
