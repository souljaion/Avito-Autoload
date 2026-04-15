"""Tests for Telegram notification service."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.telegram_notify import send_message, notify_declined


class TestSendMessage:
    @pytest.mark.asyncio
    async def test_send_message_no_token(self):
        """Should return False if TELEGRAM_BOT_TOKEN is empty."""
        with patch("app.services.telegram_notify.settings") as mock_settings:
            mock_settings.TELEGRAM_BOT_TOKEN = ""
            mock_settings.TELEGRAM_CHAT_ID = "12345"
            result = await send_message("hello")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_message_no_chat_id(self):
        """Should return False if TELEGRAM_CHAT_ID is empty."""
        with patch("app.services.telegram_notify.settings") as mock_settings:
            mock_settings.TELEGRAM_BOT_TOKEN = "bot:token"
            mock_settings.TELEGRAM_CHAT_ID = ""
            result = await send_message("hello")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_message_success(self):
        """Should return True on 200 response."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.telegram_notify.settings") as mock_settings, \
             patch("app.services.telegram_notify.httpx.AsyncClient", return_value=mock_client):
            mock_settings.TELEGRAM_BOT_TOKEN = "bot:token123"
            mock_settings.TELEGRAM_CHAT_ID = "99999"
            result = await send_message("Test notification")

        assert result is True
        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        assert call_kwargs[1]["json"]["chat_id"] == "99999"
        assert call_kwargs[1]["json"]["text"] == "Test notification"
        assert call_kwargs[1]["json"]["parse_mode"] == "HTML"

    @pytest.mark.asyncio
    async def test_send_message_api_error(self):
        """Should return False on non-200 response."""
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.text = "Forbidden"

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.telegram_notify.settings") as mock_settings, \
             patch("app.services.telegram_notify.httpx.AsyncClient", return_value=mock_client):
            mock_settings.TELEGRAM_BOT_TOKEN = "bot:token"
            mock_settings.TELEGRAM_CHAT_ID = "12345"
            result = await send_message("test")

        assert result is False

    @pytest.mark.asyncio
    async def test_send_message_exception(self):
        """Should return False on httpx exception."""
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.telegram_notify.settings") as mock_settings, \
             patch("app.services.telegram_notify.httpx.AsyncClient", return_value=mock_client):
            mock_settings.TELEGRAM_BOT_TOKEN = "bot:token"
            mock_settings.TELEGRAM_CHAT_ID = "12345"
            result = await send_message("test")

        assert result is False


class TestNotifyDeclined:
    @pytest.mark.asyncio
    async def test_notify_declined_calls_send_message(self):
        """notify_declined should format text and call send_message."""
        with patch("app.services.telegram_notify.send_message", new_callable=AsyncMock, return_value=True) as mock_send:
            result = await notify_declined("MyShop", 3, 10, 42)

        assert result is True
        mock_send.assert_called_once()
        text = mock_send.call_args[0][0]
        assert "MyShop" in text
        assert "3" in text
        assert "10" in text
        assert "42" in str(text)

    @pytest.mark.asyncio
    async def test_notify_declined_returns_false_on_failure(self):
        """notify_declined should return False when send_message fails."""
        with patch("app.services.telegram_notify.send_message", new_callable=AsyncMock, return_value=False):
            result = await notify_declined("Shop", 1, 5, 99)

        assert result is False
