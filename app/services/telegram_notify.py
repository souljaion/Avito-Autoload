"""Send Telegram notifications. Silently does nothing if token is not configured."""

import structlog
import httpx

from app.config import settings

logger = structlog.get_logger(__name__)

TELEGRAM_API = "https://api.telegram.org"


async def send_message(text: str) -> bool:
    """Send a message to the configured Telegram chat. Returns True on success."""
    token = settings.TELEGRAM_BOT_TOKEN
    chat_id = settings.TELEGRAM_CHAT_ID

    if not token or not chat_id:
        return False

    url = f"{TELEGRAM_API}/bot{token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
            })
            if resp.status_code != 200:
                logger.warning("Telegram API error", status=resp.status_code, body=resp.text[:200])
                return False
            return True
    except Exception:
        logger.exception("Failed to send Telegram notification")
        return False


async def notify_declined(account_name: str, declined_ads: int, total_ads: int, report_id: int) -> bool:
    """Send notification about declined ads in an Avito report."""
    text = (
        f"\u26a0\ufe0f Avito отчёт [<b>{account_name}</b>]: "
        f"{declined_ads} отклонено из {total_ads}\n"
        f"Подробности: https://autoload.souljaion.ru/reports/{report_id}"
    )
    return await send_message(text)
