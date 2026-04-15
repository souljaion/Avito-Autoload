"""Tests for AvitoClient reconciliation methods: avito_ids <-> ad_ids mapping."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.avito_client import AvitoClient


def _make_client():
    account = MagicMock()
    account.access_token = "test_token"
    account.token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    account.client_id = "test_id"
    account.client_secret = "test_secret"
    db = AsyncMock()
    client = AvitoClient(account, db)
    client._client = AsyncMock()
    return client


class TestGetAdIdsByAvitoIds:
    @pytest.mark.asyncio
    async def test_happy_path(self):
        """Maps avito_ids to ad_ids correctly."""
        client = _make_client()

        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "items": [
                {"avito_id": 100, "ad_id": "abc"},
                {"avito_id": 200, "ad_id": "def"},
            ]
        }
        resp.raise_for_status = MagicMock()
        client._client.request = AsyncMock(return_value=resp)

        result = await client.get_ad_ids_by_avito_ids([100, 200])

        assert result == {100: "abc", 200: "def"}
        await client.close()

    @pytest.mark.asyncio
    async def test_error_returns_empty(self):
        """On API error, returns empty dict without raising."""
        client = _make_client()
        client._client.request = AsyncMock(side_effect=Exception("API error"))

        result = await client.get_ad_ids_by_avito_ids([100])

        assert result == {}
        await client.close()


class TestGetAvitoIdsByAdIds:
    @pytest.mark.asyncio
    async def test_happy_path(self):
        """Maps ad_ids to avito_ids correctly."""
        client = _make_client()

        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "items": [
                {"ad_id": "abc", "avito_id": 100},
                {"ad_id": "def", "avito_id": 200},
            ]
        }
        resp.raise_for_status = MagicMock()
        client._client.request = AsyncMock(return_value=resp)

        result = await client.get_avito_ids_by_ad_ids(["abc", "def"])

        assert result == {"abc": 100, "def": 200}
        await client.close()

    @pytest.mark.asyncio
    async def test_error_returns_empty(self):
        """On API error, returns empty dict without raising."""
        client = _make_client()
        client._client.request = AsyncMock(side_effect=Exception("timeout"))

        result = await client.get_avito_ids_by_ad_ids(["abc"])

        assert result == {}
        await client.close()
