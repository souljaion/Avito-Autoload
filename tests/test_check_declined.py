"""Tests for _job_check_declined_ads: blocked/rejected/removed detection."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from contextlib import asynccontextmanager

import pytest

from app.scheduler import _job_check_declined_ads


def _make_product(pid, status="active", avito_id=111, version=1, removed_at=None, extra=None):
    p = MagicMock()
    p.id = pid
    p.status = status
    p.avito_id = avito_id
    p.version = version
    p.removed_at = removed_at
    p.title = f"Product {pid}"
    p.extra = extra if extra is not None else {}
    p.account_id = 1
    return p


def _make_account(acc_id=1):
    a = MagicMock()
    a.id = acc_id
    a.name = "TestAcc"
    a.access_token = "tok"
    a.client_id = "cid"
    a.client_secret = "sec"
    return a


def _make_avito_status_item(ad_id, avito_status, messages=None):
    return {
        "ad_id": str(ad_id),
        "avito_id": 111,
        "avito_status": avito_status,
        "url": "https://avito.ru/item/111",
        "messages": messages or [],
        "processing_time": None,
        "avito_date_end": None,
        "fee_info": None,
    }


def _setup_mocks(products, avito_items, safe_update_return=True):
    """Set up all patches needed by _job_check_declined_ads.

    Returns a dict of mock objects for assertions.
    """
    account = _make_account()
    for p in products:
        p.account = account

    # Mock db.execute for the products query
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = products
    result_mock = MagicMock()
    result_mock.scalars.return_value = scalars_mock

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=result_mock)
    mock_db.commit = AsyncMock()

    # async_session context manager
    @asynccontextmanager
    async def mock_session():
        yield mock_db

    mocks = {
        "db": mock_db,
        "account": account,
        "products": products,
    }

    # Build patches
    mocks["patches"] = {
        "async_session": patch("app.scheduler.async_session", mock_session),
        "AvitoClient": patch("app.scheduler._job_check_declined_ads.__code__", None),  # placeholder
        "safe_update": patch("app.db.safe_update_status",
                             new_callable=AsyncMock, return_value=safe_update_return, create=True),
        "send_message": patch("app.scheduler._job_check_declined_ads.__code__", None),  # placeholder
    }

    return mocks


class TestCheckDeclinedAds:
    @pytest.mark.asyncio
    async def test_blocked_product_set_to_paused(self):
        """Blocked ad should trigger safe_update_status with 'paused'."""
        product = _make_product(10, status="active")
        account = _make_account()
        product.account = account

        scalars = MagicMock()
        scalars.all.return_value = [product]
        result = MagicMock()
        result.scalars.return_value = scalars

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=result)
        mock_db.commit = AsyncMock()

        @asynccontextmanager
        async def mock_session():
            yield mock_db

        blocked_messages = [{"title": "Нарушение", "description": "Запрещённый товар",
                             "type": "error", "code": 1}]
        avito_items = [_make_avito_status_item(10, "blocked", messages=blocked_messages)]

        with patch("app.scheduler.async_session", mock_session), \
             patch("app.services.avito_client.AvitoClient") as MockClient, \
             patch("app.db.safe_update_status", new_callable=AsyncMock, return_value=True) as mock_safe, \
             patch("app.services.telegram_notify.send_message", new_callable=AsyncMock) as mock_send:
            client_inst = AsyncMock()
            client_inst.get_items_info = AsyncMock(return_value=avito_items)
            client_inst.close = AsyncMock()
            MockClient.return_value = client_inst

            await _job_check_declined_ads()

        mock_safe.assert_called_once()
        call_args = mock_safe.call_args
        assert call_args[0][2] == "paused"  # new_status
        assert call_args[0][1] == 10  # product_id
        mock_send.assert_called_once()
        assert "🚫" in mock_send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_rejected_product_set_to_paused(self):
        """Rejected ad should also trigger 'paused' status."""
        product = _make_product(20, status="active")
        account = _make_account()
        product.account = account

        scalars = MagicMock()
        scalars.all.return_value = [product]
        result = MagicMock()
        result.scalars.return_value = scalars

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=result)
        mock_db.commit = AsyncMock()

        @asynccontextmanager
        async def mock_session():
            yield mock_db

        avito_items = [_make_avito_status_item(20, "rejected")]

        with patch("app.scheduler.async_session", mock_session), \
             patch("app.services.avito_client.AvitoClient") as MockClient, \
             patch("app.db.safe_update_status", new_callable=AsyncMock, return_value=True) as mock_safe, \
             patch("app.services.telegram_notify.send_message", new_callable=AsyncMock):
            client_inst = AsyncMock()
            client_inst.get_items_info = AsyncMock(return_value=avito_items)
            client_inst.close = AsyncMock()
            MockClient.return_value = client_inst

            await _job_check_declined_ads()

        assert mock_safe.call_args[0][2] == "paused"

    @pytest.mark.asyncio
    async def test_removed_product_soft_deleted(self):
        """Removed ad should trigger safe_update_status with 'removed' + removed_at."""
        product = _make_product(30, status="active", removed_at=None)
        account = _make_account()
        product.account = account

        scalars = MagicMock()
        scalars.all.return_value = [product]
        result = MagicMock()
        result.scalars.return_value = scalars

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=result)
        mock_db.commit = AsyncMock()

        @asynccontextmanager
        async def mock_session():
            yield mock_db

        avito_items = [_make_avito_status_item(30, "removed")]

        with patch("app.scheduler.async_session", mock_session), \
             patch("app.services.avito_client.AvitoClient") as MockClient, \
             patch("app.db.safe_update_status", new_callable=AsyncMock, return_value=True) as mock_safe, \
             patch("app.services.telegram_notify.send_message", new_callable=AsyncMock):
            client_inst = AsyncMock()
            client_inst.get_items_info = AsyncMock(return_value=avito_items)
            client_inst.close = AsyncMock()
            MockClient.return_value = client_inst

            await _job_check_declined_ads()

        mock_safe.assert_called_once()
        assert mock_safe.call_args[0][2] == "removed"
        extra_fields = mock_safe.call_args[1].get("extra_fields") or mock_safe.call_args[0][4] if len(mock_safe.call_args[0]) > 4 else None
        # extra_fields passed as kwarg
        kw = mock_safe.call_args.kwargs
        assert "removed_at" in kw.get("extra_fields", {})

    @pytest.mark.asyncio
    async def test_conflict_skipped_gracefully(self):
        """When safe_update_status returns False, skip without error or notification."""
        product = _make_product(40, status="active")
        account = _make_account()
        product.account = account

        scalars = MagicMock()
        scalars.all.return_value = [product]
        result = MagicMock()
        result.scalars.return_value = scalars

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=result)
        mock_db.commit = AsyncMock()

        @asynccontextmanager
        async def mock_session():
            yield mock_db

        avito_items = [_make_avito_status_item(40, "blocked")]

        with patch("app.scheduler.async_session", mock_session), \
             patch("app.services.avito_client.AvitoClient") as MockClient, \
             patch("app.db.safe_update_status", new_callable=AsyncMock, return_value=False) as mock_safe, \
             patch("app.services.telegram_notify.send_message", new_callable=AsyncMock) as mock_send:
            client_inst = AsyncMock()
            client_inst.get_items_info = AsyncMock(return_value=avito_items)
            client_inst.close = AsyncMock()
            MockClient.return_value = client_inst

            await _job_check_declined_ads()  # should not raise

        mock_safe.assert_called_once()
        mock_send.assert_not_called()  # no telegram on conflict

    @pytest.mark.asyncio
    async def test_active_product_restored_from_paused(self):
        """Paused product that is active on Avito should be restored."""
        product = _make_product(50, status="paused", extra={"avito_messages": [{"title": "Old"}]})
        account = _make_account()
        product.account = account

        scalars = MagicMock()
        scalars.all.return_value = [product]
        result = MagicMock()
        result.scalars.return_value = scalars

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=result)
        mock_db.commit = AsyncMock()

        @asynccontextmanager
        async def mock_session():
            yield mock_db

        avito_items = [_make_avito_status_item(50, "active")]

        with patch("app.scheduler.async_session", mock_session), \
             patch("app.services.avito_client.AvitoClient") as MockClient, \
             patch("app.db.safe_update_status", new_callable=AsyncMock, return_value=True) as mock_safe, \
             patch("app.services.telegram_notify.send_message", new_callable=AsyncMock):
            client_inst = AsyncMock()
            client_inst.get_items_info = AsyncMock(return_value=avito_items)
            client_inst.close = AsyncMock()
            MockClient.return_value = client_inst

            await _job_check_declined_ads()

        mock_safe.assert_called_once()
        assert mock_safe.call_args[0][2] == "active"
        # extra_fields should have avito_messages cleared
        kw = mock_safe.call_args.kwargs
        extra = kw.get("extra_fields", {}).get("extra", {})
        assert "avito_messages" not in (extra or {})

    @pytest.mark.asyncio
    async def test_already_removed_product_skipped(self):
        """Product already removed (status=removed, removed_at set) should not be updated."""
        product = _make_product(60, status="removed", removed_at=datetime.now(timezone.utc).replace(tzinfo=None))
        account = _make_account()
        product.account = account

        scalars = MagicMock()
        scalars.all.return_value = [product]
        result = MagicMock()
        result.scalars.return_value = scalars

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=result)
        mock_db.commit = AsyncMock()

        @asynccontextmanager
        async def mock_session():
            yield mock_db

        avito_items = [_make_avito_status_item(60, "removed")]

        with patch("app.scheduler.async_session", mock_session), \
             patch("app.services.avito_client.AvitoClient") as MockClient, \
             patch("app.db.safe_update_status", new_callable=AsyncMock) as mock_safe, \
             patch("app.services.telegram_notify.send_message", new_callable=AsyncMock):
            client_inst = AsyncMock()
            client_inst.get_items_info = AsyncMock(return_value=avito_items)
            client_inst.close = AsyncMock()
            MockClient.return_value = client_inst

            await _job_check_declined_ads()

        # The product query only returns status IN (active, published, imported),
        # but here we set status="removed" — so the code sees it as not matching
        # the "removed" branch condition (product.status != "removed" → False)
        mock_safe.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_products_no_api_calls(self):
        """Empty product list should not trigger any AvitoClient calls."""
        scalars = MagicMock()
        scalars.all.return_value = []
        result = MagicMock()
        result.scalars.return_value = scalars

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=result)
        mock_db.commit = AsyncMock()

        @asynccontextmanager
        async def mock_session():
            yield mock_db

        with patch("app.scheduler.async_session", mock_session), \
             patch("app.services.avito_client.AvitoClient") as MockClient, \
             patch("app.db.safe_update_status", new_callable=AsyncMock), \
             patch("app.services.telegram_notify.send_message", new_callable=AsyncMock):

            await _job_check_declined_ads()

        MockClient.assert_not_called()

    @pytest.mark.asyncio
    async def test_multiple_products_processed(self):
        """Multiple products from same account should all be checked."""
        account = _make_account()
        p1 = _make_product(1, status="active")
        p2 = _make_product(2, status="active")
        p3 = _make_product(3, status="active")
        for p in [p1, p2, p3]:
            p.account = account

        scalars = MagicMock()
        scalars.all.return_value = [p1, p2, p3]
        result = MagicMock()
        result.scalars.return_value = scalars

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=result)
        mock_db.commit = AsyncMock()

        @asynccontextmanager
        async def mock_session():
            yield mock_db

        avito_items = [
            _make_avito_status_item(1, "blocked"),
            _make_avito_status_item(2, "active"),
            _make_avito_status_item(3, "removed"),
        ]

        with patch("app.scheduler.async_session", mock_session), \
             patch("app.services.avito_client.AvitoClient") as MockClient, \
             patch("app.db.safe_update_status", new_callable=AsyncMock, return_value=True) as mock_safe, \
             patch("app.services.telegram_notify.send_message", new_callable=AsyncMock):
            client_inst = AsyncMock()
            client_inst.get_items_info = AsyncMock(return_value=avito_items)
            client_inst.close = AsyncMock()
            MockClient.return_value = client_inst

            await _job_check_declined_ads()

        # p1 → paused (blocked), p2 → no change (active stays active), p3 → removed
        assert mock_safe.call_count == 2  # p1 and p3
        statuses = [c[0][2] for c in mock_safe.call_args_list]
        assert "paused" in statuses
        assert "removed" in statuses
