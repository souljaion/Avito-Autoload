"""Tests for UUID feed token access."""

import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from app.db import get_db
from app.routes.feeds import router


def _make_app(mock_db):
    app = FastAPI()
    app.include_router(router)

    async def override_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_db
    return app


def _make_account(acc_id=1, feed_token=None):
    a = MagicMock()
    a.id = acc_id
    a.name = "TestAcc"
    a.feed_token = feed_token or str(uuid.uuid4())
    return a


class TestFeedTokenAccess:
    @pytest.mark.asyncio
    async def test_valid_token_serves_xml(self, tmp_path):
        """Correct feed_token returns XML content."""
        token = str(uuid.uuid4())
        acc = _make_account(acc_id=1, feed_token=token)

        # Create a fake XML file
        feeds_dir = str(tmp_path)
        xml_path = os.path.join(feeds_dir, "1.xml")
        with open(xml_path, "wb") as f:
            f.write(b"<Ads/>")

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = acc

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        app = _make_app(mock_db)

        with patch("app.routes.feeds.settings") as mock_settings:
            mock_settings.FEEDS_DIR = feeds_dir
            mock_settings.BASE_URL = "http://test"
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get(f"/feeds/{token}.xml")

        assert resp.status_code == 200
        assert resp.text == "<Ads/>"
        assert resp.headers["content-type"] == "application/xml"

    @pytest.mark.asyncio
    async def test_wrong_token_returns_404(self):
        """Invalid token returns 404."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/feeds/{uuid.uuid4()}.xml")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_numeric_id_returns_404(self):
        """Old numeric URL returns 404 (no account has numeric feed_token)."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/feeds/1.xml")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_token_found_but_xml_missing(self, tmp_path):
        """Valid token but XML file not on disk returns 404."""
        token = str(uuid.uuid4())
        acc = _make_account(acc_id=99, feed_token=token)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = acc

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        app = _make_app(mock_db)

        with patch("app.routes.feeds.settings") as mock_settings:
            mock_settings.FEEDS_DIR = str(tmp_path)
            mock_settings.BASE_URL = "http://test"
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get(f"/feeds/{token}.xml")

        assert resp.status_code == 404
