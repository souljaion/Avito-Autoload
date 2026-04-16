"""Tests for app/services/feed_importer.py + POST /sync-from-feed."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from app.db import get_db
from app.routes.autoload import router as autoload_router
from app.services.feed_importer import (
    sync_avito_ids_from_feed,
    _extract_feed_url,
    _parse_feed_xml,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_account(id=1, name="Zulla"):
    acc = MagicMock()
    acc.id = id
    acc.name = name
    acc.client_id = "cid"
    acc.client_secret = "sec"
    acc.access_token = "tok"
    acc.token_expires_at = datetime.utcnow() + timedelta(hours=1)
    return acc


def _make_xml(ads: list[dict]) -> bytes:
    """Build a minimal Avito autoload-style XML feed.

    Each ad dict may contain: avito_id, ad_id, title, status.
    """
    parts = ['<?xml version="1.0" encoding="UTF-8"?>', '<Ads formatVersion="3" target="Avito.ru">']
    for a in ads:
        parts.append("  <Ad>")
        if a.get("ad_id") is not None:
            parts.append(f"    <Id>{a['ad_id']}</Id>")
        if a.get("avito_id") is not None:
            parts.append(f"    <AvitoId>{a['avito_id']}</AvitoId>")
        if a.get("title") is not None:
            parts.append(f"    <Title>{a['title']}</Title>")
        if a.get("status") is not None:
            parts.append(f"    <Status>{a['status']}</Status>")
        parts.append("  </Ad>")
    parts.append("</Ads>")
    return "\n".join(parts).encode("utf-8")


def _build_db(*, existing_avito_ids=None, null_products=None, global_avito_ids=None):
    """Mock DB with the 3 SELECT calls feed_importer makes, in order."""
    def _scalars(items):
        s = MagicMock()
        s.all.return_value = items or []
        r = MagicMock()
        r.scalars.return_value = s
        return r

    def _rows(rows):
        r = MagicMock()
        r.all.return_value = rows or []
        return r

    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    added: list = []
    db.add = MagicMock(side_effect=added.append)

    db.execute = AsyncMock(side_effect=[
        _rows([(x,) for x in (existing_avito_ids or [])]),  # per-account avito_ids
        _scalars(null_products or []),                       # null avito_id products
        _rows([(x,) for x in (global_avito_ids or [])]),     # global avito_ids
    ])
    db.added = added
    return db


def _build_client(*, profile=None, profile_exc=None, xml_bytes=None, xml_exc=None):
    """Mock AvitoClient + patch httpx.AsyncClient used to download the feed."""
    client = AsyncMock()
    if profile_exc:
        client.get_autoload_profile = AsyncMock(side_effect=profile_exc)
    else:
        client.get_autoload_profile = AsyncMock(return_value=profile or {})
    client._headers = AsyncMock(return_value={"Authorization": "Bearer tok"})
    client.close = AsyncMock()
    return client


def _patch_httpx_get(xml_bytes=None, exc=None):
    """Return a context-manager mock for httpx.AsyncClient(...).get()."""
    resp = MagicMock()
    if exc:
        get = AsyncMock(side_effect=exc)
    else:
        resp.content = xml_bytes or b""
        resp.raise_for_status = MagicMock()
        get = AsyncMock(return_value=resp)

    inst = AsyncMock()
    inst.get = get
    inst.__aenter__ = AsyncMock(return_value=inst)
    inst.__aexit__ = AsyncMock(return_value=None)
    return patch("app.services.feed_importer.httpx.AsyncClient", return_value=inst)


# ---------------------------------------------------------------------------
# _extract_feed_url
# ---------------------------------------------------------------------------

class TestExtractFeedUrl:
    def test_prefers_feeds_data(self):
        url = _extract_feed_url({
            "feeds_data": [{"name": "main", "url": "https://example.com/new.xml"}],
            "upload_url": "https://example.com/legacy.xml",
        })
        assert url == "https://example.com/new.xml"

    def test_falls_back_to_upload_url_when_feeds_data_empty(self):
        url = _extract_feed_url({
            "feeds_data": [],
            "upload_url": "https://example.com/legacy.xml",
        })
        assert url == "https://example.com/legacy.xml"

    def test_falls_back_when_feeds_data_missing(self):
        url = _extract_feed_url({"upload_url": "https://example.com/legacy.xml"})
        assert url == "https://example.com/legacy.xml"

    def test_returns_none_when_nothing(self):
        assert _extract_feed_url({}) is None
        assert _extract_feed_url({"feeds_data": [], "upload_url": ""}) is None


# ---------------------------------------------------------------------------
# _parse_feed_xml
# ---------------------------------------------------------------------------

class TestParseFeedXml:
    def test_parses_complete_ad(self):
        xml = _make_xml([{"ad_id": "A1", "avito_id": 1234, "title": "Nike"}])
        ads = _parse_feed_xml(xml)
        assert len(ads) == 1
        assert ads[0]["avito_id"] == 1234
        assert ads[0]["ad_id"] == "A1"
        assert ads[0]["title"] == "Nike"
        assert ads[0]["status"] is None

    def test_handles_missing_avito_id(self):
        xml = _make_xml([{"ad_id": "A1", "title": "No avito id yet"}])
        ads = _parse_feed_xml(xml)
        assert ads[0]["avito_id"] is None

    def test_handles_status_removed(self):
        xml = _make_xml([{"avito_id": 99, "ad_id": "A2", "status": "Removed"}])
        ads = _parse_feed_xml(xml)
        assert ads[0]["status"] == "Removed"

    def test_invalid_xml_raises(self):
        with pytest.raises(ValueError, match="Invalid XML"):
            _parse_feed_xml(b"not xml at all")


# ---------------------------------------------------------------------------
# sync_avito_ids_from_feed — happy paths
# ---------------------------------------------------------------------------

class TestSyncAvitoIdsFromFeed:
    @pytest.mark.asyncio
    async def test_extracts_url_from_feeds_data(self):
        """feeds_data populated → that URL is downloaded, not upload_url."""
        account = _make_account()
        db = _build_db()
        db.get = AsyncMock(return_value=account)

        profile = {
            "feeds_data": [{"name": "main", "url": "https://acme.example/feed.xml"}],
            "upload_url": "https://other.example/legacy.xml",
        }
        client = _build_client(profile=profile)

        captured_url = {}

        resp = MagicMock()
        resp.content = _make_xml([])
        resp.raise_for_status = MagicMock()

        async def fake_get(url, headers=None):
            captured_url["u"] = url
            return resp

        inst = AsyncMock()
        inst.get = fake_get
        inst.__aenter__ = AsyncMock(return_value=inst)
        inst.__aexit__ = AsyncMock(return_value=None)

        with patch("app.services.feed_importer.httpx.AsyncClient", return_value=inst):
            result = await sync_avito_ids_from_feed(1, db, client=client)

        assert captured_url["u"] == "https://acme.example/feed.xml"
        assert result["error"] is None

    @pytest.mark.asyncio
    async def test_falls_back_to_upload_url_when_feeds_data_empty(self):
        account = _make_account()
        db = _build_db()
        db.get = AsyncMock(return_value=account)

        profile = {"feeds_data": [], "upload_url": "https://legacy.example/feed.xml"}
        client = _build_client(profile=profile)

        captured_url = {}
        resp = MagicMock()
        resp.content = _make_xml([])
        resp.raise_for_status = MagicMock()

        async def fake_get(url, headers=None):
            captured_url["u"] = url
            return resp

        inst = AsyncMock()
        inst.get = fake_get
        inst.__aenter__ = AsyncMock(return_value=inst)
        inst.__aexit__ = AsyncMock(return_value=None)

        with patch("app.services.feed_importer.httpx.AsyncClient", return_value=inst):
            result = await sync_avito_ids_from_feed(1, db, client=client)

        assert captured_url["u"] == "https://legacy.example/feed.xml"
        assert result["error"] is None

    @pytest.mark.asyncio
    async def test_three_ads_two_match_one_creates(self):
        """2 existing imported with NULL avito_id match by title; 3rd is new."""
        account = _make_account()

        existing1 = MagicMock(id=10, avito_id=None, title="Nike Pegasus 40", account_id=1)
        existing2 = MagicMock(id=11, avito_id=None, title="Adidas Ultraboost", account_id=1)

        db = _build_db(null_products=[existing1, existing2])
        db.get = AsyncMock(return_value=account)

        client = _build_client(profile={
            "feeds_data": [{"name": "x", "url": "https://example.com/feed.xml"}],
        })

        xml = _make_xml([
            {"ad_id": "1", "avito_id": 100001, "title": "Nike Pegasus 40"},
            {"ad_id": "2", "avito_id": 100002, "title": "Adidas Ultraboost"},
            {"ad_id": "3", "avito_id": 100003, "title": "Brand New Item"},
        ])
        with _patch_httpx_get(xml_bytes=xml):
            result = await sync_avito_ids_from_feed(1, db, client=client)

        assert result["matched"] == 2
        assert result["created"] == 1
        assert result["skipped"] == 0
        assert result["total_in_feed"] == 3
        assert result["error"] is None
        assert existing1.avito_id == 100001
        assert existing2.avito_id == 100002
        assert len(db.added) == 1
        assert db.added[0].avito_id == 100003

    @pytest.mark.asyncio
    async def test_status_removed_is_skipped(self):
        account = _make_account()
        db = _build_db()
        db.get = AsyncMock(return_value=account)

        client = _build_client(profile={
            "feeds_data": [{"name": "x", "url": "https://example.com/feed.xml"}],
        })

        xml = _make_xml([
            {"ad_id": "1", "avito_id": 200001, "title": "Some", "status": "Removed"},
        ])
        with _patch_httpx_get(xml_bytes=xml):
            result = await sync_avito_ids_from_feed(1, db, client=client)

        assert result["skipped"] == 1
        assert result["matched"] == 0
        assert result["created"] == 0
        assert db.added == []

    @pytest.mark.asyncio
    async def test_avito_id_already_in_db_is_skipped(self):
        account = _make_account()
        db = _build_db(existing_avito_ids=[300001])
        db.get = AsyncMock(return_value=account)

        client = _build_client(profile={
            "feeds_data": [{"name": "x", "url": "https://example.com/feed.xml"}],
        })

        xml = _make_xml([
            {"ad_id": "1", "avito_id": 300001, "title": "Already known"},
        ])
        with _patch_httpx_get(xml_bytes=xml):
            result = await sync_avito_ids_from_feed(1, db, client=client)

        assert result["skipped"] == 1
        assert result["matched"] == 0
        assert result["created"] == 0
        assert db.added == []

    @pytest.mark.asyncio
    async def test_fuzzy_title_match_case_and_whitespace(self):
        account = _make_account()
        existing = MagicMock(id=20, avito_id=None, title="New Balance 990v6", account_id=1)
        db = _build_db(null_products=[existing])
        db.get = AsyncMock(return_value=account)

        client = _build_client(profile={
            "feeds_data": [{"name": "x", "url": "https://example.com/feed.xml"}],
        })

        xml = _make_xml([
            {"ad_id": "1", "avito_id": 400001, "title": "  NEW   BALANCE 990v6  "},
        ])
        with _patch_httpx_get(xml_bytes=xml):
            result = await sync_avito_ids_from_feed(1, db, client=client)

        assert result["matched"] == 1
        assert existing.avito_id == 400001


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_account_not_found(self):
        db = AsyncMock()
        db.get = AsyncMock(return_value=None)
        result = await sync_avito_ids_from_feed(999, db, client=AsyncMock())
        assert result["error"] == "Account not found"

    @pytest.mark.asyncio
    async def test_profile_404(self):
        account = _make_account()
        db = AsyncMock()
        db.get = AsyncMock(return_value=account)

        resp404 = MagicMock(status_code=404)
        client = _build_client(profile_exc=httpx.HTTPStatusError("404", request=MagicMock(), response=resp404))

        result = await sync_avito_ids_from_feed(1, db, client=client)
        assert result["error"] == "profile not found"

    @pytest.mark.asyncio
    async def test_no_feed_url_anywhere(self):
        account = _make_account()
        db = AsyncMock()
        db.get = AsyncMock(return_value=account)
        client = _build_client(profile={"feeds_data": [], "upload_url": ""})

        result = await sync_avito_ids_from_feed(1, db, client=client)
        assert result["error"] == "no feed url"

    @pytest.mark.asyncio
    async def test_network_error_on_download(self):
        account = _make_account()
        db = AsyncMock()
        db.get = AsyncMock(return_value=account)
        client = _build_client(profile={
            "feeds_data": [{"name": "x", "url": "https://example.com/feed.xml"}],
        })

        with _patch_httpx_get(exc=httpx.ConnectError("dns fail")):
            result = await sync_avito_ids_from_feed(1, db, client=client)

        assert result["error"].startswith("feed download failed")
        assert result["matched"] == 0
        assert result["created"] == 0


# ---------------------------------------------------------------------------
# POST /accounts/{id}/autoload/sync-from-feed
# ---------------------------------------------------------------------------

class TestSyncFromFeedEndpoint:
    @pytest.mark.asyncio
    async def test_endpoint_returns_200_with_counts(self):
        acc = _make_account()
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=acc)

        app = FastAPI()
        app.include_router(autoload_router)

        async def _gen():
            yield mock_db
        app.dependency_overrides[get_db] = _gen

        with patch("app.routes.autoload.sync_avito_ids_from_feed", new_callable=AsyncMock) as mock_svc:
            mock_svc.return_value = {
                "matched": 120, "created": 5, "skipped": 11,
                "total_in_feed": 136, "error": None,
            }
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                resp = await c.post("/accounts/1/autoload/sync-from-feed")

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["matched"] == 120
        assert data["created"] == 5
        assert data["skipped"] == 11
        assert data["total_in_feed"] == 136

    @pytest.mark.asyncio
    async def test_endpoint_404_for_unknown_account(self):
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)

        app = FastAPI()
        app.include_router(autoload_router)
        async def _gen():
            yield mock_db
        app.dependency_overrides[get_db] = _gen

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/accounts/999/autoload/sync-from-feed")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_endpoint_502_on_service_error(self):
        acc = _make_account()
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=acc)

        app = FastAPI()
        app.include_router(autoload_router)
        async def _gen():
            yield mock_db
        app.dependency_overrides[get_db] = _gen

        with patch("app.routes.autoload.sync_avito_ids_from_feed", new_callable=AsyncMock) as mock_svc:
            mock_svc.return_value = {
                "matched": 0, "created": 0, "skipped": 0,
                "total_in_feed": 0, "error": "feed download failed: timeout",
            }
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                resp = await c.post("/accounts/1/autoload/sync-from-feed")
        assert resp.status_code == 502
        assert resp.json()["ok"] is False
        assert "feed download" in resp.json()["error"]
