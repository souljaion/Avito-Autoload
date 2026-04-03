import asyncio
from datetime import datetime, timedelta, timezone

import structlog

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account

logger = structlog.get_logger(__name__)

AVITO_AUTH_URL = "https://api.avito.ru/token"
AVITO_API_BASE = "https://api.avito.ru"

# Retry config
MAX_RETRIES_429 = 3
MAX_RETRIES_5XX = 2
BACKOFF_BASE = 1.0  # seconds


class AvitoClient:
    def __init__(self, account: Account, db: AsyncSession):
        self.account = account
        self.db = db
        self._client = httpx.AsyncClient(timeout=30.0)

    async def close(self):
        await self._client.aclose()

    async def _ensure_token(self):
        now = datetime.now(timezone.utc)
        if self.account.access_token and self.account.token_expires_at:
            expires = self.account.token_expires_at
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if expires > now:
                return

        if not self.account.client_id or not self.account.client_secret:
            raise ValueError("Account missing client_id or client_secret")

        resp = await self._client.post(AVITO_AUTH_URL, data={
            "grant_type": "client_credentials",
            "client_id": self.account.client_id,
            "client_secret": self.account.client_secret,
        })
        resp.raise_for_status()
        data = resp.json()

        self.account.access_token = data["access_token"]
        expires_in = data.get("expires_in", 86400)
        self.account.token_expires_at = datetime.fromtimestamp(
            now.timestamp() + expires_in, tz=timezone.utc
        ).replace(tzinfo=None)
        await self.db.commit()

    async def _headers(self) -> dict:
        await self._ensure_token()
        return {
            "Authorization": f"Bearer {self.account.access_token}",
            "Content-Type": "application/json",
        }

    async def _request_with_retry(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Execute HTTP request with retry on 429/5xx using exponential backoff."""
        attempt = 0
        while True:
            resp = await self._client.request(method, url, **kwargs)

            if resp.status_code == 429:
                attempt += 1
                if attempt > MAX_RETRIES_429:
                    resp.raise_for_status()
                wait = BACKOFF_BASE * (2 ** (attempt - 1))
                retry_after = resp.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    wait = max(wait, int(retry_after))
                logger.warning("Avito 429 rate limit, retry %d/%d in %.1fs: %s",
                               attempt, MAX_RETRIES_429, wait, url)
                await asyncio.sleep(wait)
                continue

            if resp.status_code >= 500:
                attempt += 1
                if attempt > MAX_RETRIES_5XX:
                    resp.raise_for_status()
                wait = BACKOFF_BASE * (2 ** (attempt - 1))
                logger.warning("Avito %d server error, retry %d/%d in %.1fs: %s",
                               resp.status_code, attempt, MAX_RETRIES_5XX, wait, url)
                await asyncio.sleep(wait)
                continue

            return resp

    async def get_profile(self) -> dict:
        headers = await self._headers()
        resp = await self._request_with_retry(
            "GET", f"{AVITO_API_BASE}/autoload/v1/profile", headers=headers,
        )
        resp.raise_for_status()
        return resp.json()

    async def update_profile(self, feed_url: str) -> dict:
        """Update autoload profile with new feed URL."""
        current = await self.get_profile()

        payload = {
            "upload_url": feed_url,
            "autoload_enabled": current.get("autoload_enabled", True),
            "schedule": current.get("schedule", [{
                "rate": -1,
                "weekdays": [0, 1, 2, 3, 4, 5, 6],
                "time_slots": list(range(24)),
            }]),
        }
        report_email = current.get("report_email")
        if report_email:
            payload["report_email"] = report_email

        headers = await self._headers()
        resp = await self._request_with_retry(
            "POST", f"{AVITO_API_BASE}/autoload/v1/profile",
            headers=headers, json=payload,
        )
        if resp.status_code == 400:
            data = resp.json()
            error = data.get("error", {})
            msg = error.get("message", str(data)) if isinstance(error, dict) else str(error)
            raise ValueError(f"Avito отклонил запрос: {msg}")
        resp.raise_for_status()
        return await self.get_profile()

    async def upload(self) -> dict:
        headers = await self._headers()
        resp = await self._request_with_retry(
            "POST", f"{AVITO_API_BASE}/autoload/v2/upload", headers=headers,
        )
        resp.raise_for_status()
        return resp.json()

    async def upload_feed(self, xml_bytes: bytes, filename: str = "feed.xml") -> dict:
        """Upload XML feed file to Avito Autoload API via multipart/form-data."""
        await self._ensure_token()
        headers = {"Authorization": f"Bearer {self.account.access_token}"}
        resp = await self._request_with_retry(
            "POST", f"{AVITO_API_BASE}/autoload/v1/upload",
            headers=headers,
            files={"file": (filename, xml_bytes, "application/xml")},
            timeout=60.0,
        )
        body = resp.text.strip()
        data = resp.json() if body else {}

        if resp.status_code == 429:
            error_msg = "Автозагрузка уже запущена. Повторите через 1 час."
            if isinstance(data.get("error"), dict):
                error_msg = data["error"].get("message", error_msg)
            raise ValueError(error_msg)
        if resp.status_code == 401:
            raise ValueError("Токен недействителен (401 Unauthorized)")
        if resp.status_code >= 400:
            resp.raise_for_status()
        return data

    async def get_user_items(self, status: str = "active", per_page: int = 50) -> list[dict]:
        """Fetch user's items from Avito core API with pagination."""
        headers = await self._headers()
        all_items: list[dict] = []
        page = 1
        while True:
            resp = await self._request_with_retry(
                "GET", f"{AVITO_API_BASE}/core/v1/items",
                headers=headers,
                params={"status": status, "per_page": per_page, "page": page},
            )
            resp.raise_for_status()
            data = resp.json()
            resources = data.get("resources") or []
            if not resources:
                break
            all_items.extend(resources)
            if len(resources) < per_page:
                break
            page += 1
        return all_items

    async def get_user_id(self) -> int:
        """Fetch Avito user ID from /core/v1/accounts/self."""
        headers = await self._headers()
        resp = await self._request_with_retry(
            "GET", f"{AVITO_API_BASE}/core/v1/accounts/self", headers=headers,
        )
        resp.raise_for_status()
        return resp.json()["id"]

    async def get_items_stats(self, user_id: int, avito_ids: list[int]) -> dict[int, dict]:
        """Fetch stats for items in batches of 200."""
        headers = await self._headers()
        now = datetime.now(timezone.utc)
        date_to = now.strftime("%Y-%m-%d")
        date_from = (now - timedelta(days=269)).strftime("%Y-%m-%d")

        result: dict[int, dict] = {}
        batch_size = 200

        for i in range(0, len(avito_ids), batch_size):
            batch = avito_ids[i:i + batch_size]
            resp = await self._request_with_retry(
                "POST", f"{AVITO_API_BASE}/stats/v1/accounts/{user_id}/items",
                headers=headers,
                json={
                    "itemIds": batch,
                    "dateFrom": date_from,
                    "dateTo": date_to,
                    "fields": ["uniqViews", "uniqContacts", "uniqFavorites"],
                },
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()

            for item in (data.get("result", {}).get("items") or []):
                avito_id = item.get("itemId")
                if not avito_id:
                    continue
                views = contacts = favorites = 0
                for stat in (item.get("stats") or []):
                    views += stat.get("uniqViews", 0)
                    contacts += stat.get("uniqContacts", 0)
                    favorites += stat.get("uniqFavorites", 0)
                result[avito_id] = {"views": views, "contacts": contacts, "favorites": favorites}

        return result

    async def get_reports(self) -> dict:
        headers = await self._headers()
        resp = await self._request_with_retry(
            "GET", f"{AVITO_API_BASE}/autoload/v2/reports", headers=headers,
        )
        resp.raise_for_status()
        return resp.json()

    async def get_report(self, report_id: int | str) -> dict:
        headers = await self._headers()
        resp = await self._request_with_retry(
            "GET", f"{AVITO_API_BASE}/autoload/v2/reports/{report_id}", headers=headers,
        )
        resp.raise_for_status()
        return resp.json()

    async def get_report_items(self, report_id: int | str, page: int = 0) -> dict:
        headers = await self._headers()
        resp = await self._request_with_retry(
            "GET", f"{AVITO_API_BASE}/autoload/v2/reports/{report_id}/items",
            headers=headers, params={"page": page, "per_page": 100},
        )
        resp.raise_for_status()
        return resp.json()
