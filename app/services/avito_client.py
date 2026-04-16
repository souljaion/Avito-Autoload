import asyncio
from datetime import datetime, timedelta, timezone

import structlog

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import decrypt
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

        try:
            plain_secret = decrypt(self.account.client_secret)
        except Exception:
            plain_secret = self.account.client_secret

        resp = await self._client.post(AVITO_AUTH_URL, data={
            "grant_type": "client_credentials",
            "client_id": self.account.client_id,
            "client_secret": plain_secret,
        })
        resp.raise_for_status()
        data = resp.json()

        if "access_token" not in data:
            error_desc = data.get("error_description") or data.get("error") or str(data)
            raise ValueError(f"Avito token response missing access_token: {error_desc}")

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
            "GET", f"{AVITO_API_BASE}/autoload/v2/profile", headers=headers,
        )
        resp.raise_for_status()
        return resp.json()

    async def get_autoload_profile(self) -> dict:
        """Fetch autoload profile via v1 endpoint.

        Returns the full payload, including feeds_data (since 2024-12-23) and
        the legacy upload_url (deprecated). Useful to discover the actual feed
        URL Avito is polling — we then download that XML to extract avito_ids.
        """
        headers = await self._headers()
        resp = await self._request_with_retry(
            "GET", f"{AVITO_API_BASE}/autoload/v1/profile", headers=headers,
        )
        resp.raise_for_status()
        return resp.json()

    async def update_profile(self, feed_url: str, feed_name: str | None = None) -> dict:
        """Update autoload profile with new feed URL (v2 API with feeds_data).

        Strategy: take the current profile as a base, override only feeds_data,
        and POST the merged payload. This preserves Avito-managed fields like
        uploadMode and allow_pay_over_limit that, if omitted, cause a 400
        "Запрос сформирован неправильно".
        """
        current = await self.get_profile()

        # Start from current state so we don't drop unknown fields
        payload = dict(current)
        payload["feeds_data"] = [{
            "feed_name": feed_name or "default",
            "feed_url": feed_url,
        }]
        # Ensure required defaults if Avito returned nulls
        if not payload.get("schedule"):
            payload["schedule"] = [{
                "rate": -1,
                "weekdays": [0, 1, 2, 3, 4, 5, 6],
                "time_slots": list(range(24)),
            }]
        if "autoload_enabled" not in payload or payload["autoload_enabled"] is None:
            payload["autoload_enabled"] = True
        # Drop nulls — Avito sometimes rejects null fields
        payload = {k: v for k, v in payload.items() if v is not None}

        headers = await self._headers()
        resp = await self._request_with_retry(
            "POST", f"{AVITO_API_BASE}/autoload/v2/profile",
            headers=headers, json=payload,
        )
        if resp.status_code == 400:
            data = resp.json()
            error = data.get("error", {})
            msg = error.get("message", str(data)) if isinstance(error, dict) else str(error)
            logger.warning("update_profile.400", account_id=self.account.id, payload_keys=list(payload.keys()), avito_error=msg)
            raise ValueError(f"Avito отклонил запрос: {msg}")
        resp.raise_for_status()
        return await self.get_profile()

    async def upload(self) -> dict:
        """Trigger Avito to download our feed from the URL stored in profile.

        Uses v1/upload — v2/upload was removed by Avito (returns 404).
        """
        headers = await self._headers()
        resp = await self._request_with_retry(
            "POST", f"{AVITO_API_BASE}/autoload/v1/upload", headers=headers,
        )
        resp.raise_for_status()
        try:
            return resp.json()
        except Exception:
            # v1/upload returns empty body on success
            return {"ok": True}

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

    async def get_all_items(self, per_page: int = 100) -> list[dict]:
        """Fetch all active items from Avito Items API with pagination.

        Returns flat list of dicts: {id, title, price, status}.
        Returns [] on any error.
        """
        try:
            headers = await self._headers()
            all_items: list[dict] = []
            page = 1
            while True:
                resp = await self._request_with_retry(
                    "GET", f"{AVITO_API_BASE}/core/v1/items",
                    headers=headers,
                    params={"status": "active", "per_page": per_page, "page": page},
                )
                resp.raise_for_status()
                data = resp.json()
                resources = data.get("resources") or []
                for r in resources:
                    all_items.append({
                        "id": r.get("id"),
                        "title": r.get("title", ""),
                        "price": r.get("price"),
                        "status": r.get("status", ""),
                    })
                if len(resources) < per_page:
                    break
                page += 1
            return all_items
        except Exception as e:
            logger.warning("get_all_items failed", account_id=self.account.id, error=str(e))
            return []

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

    async def get_item_details(self, item_id: int | str) -> dict:
        """Fetch details for a single Avito item via GET /core/v1/items?ids=N.

        NOTE: the autoload OAuth scope only exposes the listing endpoint
        (`/core/v1/items?ids=...`), not the single-item detail endpoint
        (`/core/v1/items/{id}` returns 404). Returned fields are LIMITED to:
        address, category{id,name}, id, price, status, title, url.
        Brand, params, and images are NOT available through this scope.

        Returns the first matching resource dict or {} on error / no match.
        """
        try:
            headers = await self._headers()
            resp = await self._request_with_retry(
                "GET", f"{AVITO_API_BASE}/core/v1/items",
                headers=headers, params={"ids": str(item_id)},
            )
            resp.raise_for_status()
            data = resp.json()
            resources = (data or {}).get("resources") or []
            for r in resources:
                if str(r.get("id")) == str(item_id):
                    return r if isinstance(r, dict) else {}
            return {}
        except Exception as e:
            logger.warning(
                "get_item_details failed",
                account_id=self.account.id, item_id=item_id, error=str(e),
            )
            return {}

    async def get_items_info(self, ad_ids: list[str]) -> list[dict]:
        """Fetch real-time autoload status for items by their ad_id (internal DB id).

        Calls GET /autoload/v2/reports/items with batches of 100 ids max.
        Returns list of dicts with: ad_id, avito_id, avito_status, url, messages,
        processing_time, avito_date_end, fee_info.
        """
        headers = await self._headers()
        all_items: list[dict] = []
        batch_size = 100

        for i in range(0, len(ad_ids), batch_size):
            batch = ad_ids[i:i + batch_size]
            query = ",".join(batch)
            resp = await self._request_with_retry(
                "GET",
                f"{AVITO_API_BASE}/autoload/v2/reports/items",
                headers=headers,
                params={"query": query},
            )
            resp.raise_for_status()
            data = resp.json()
            items = data.get("items") or []
            all_items.extend(items)

        return all_items

    async def get_reports(self) -> dict:
        headers = await self._headers()
        resp = await self._request_with_retry(
            "GET", f"{AVITO_API_BASE}/autoload/v3/reports", headers=headers,
        )
        resp.raise_for_status()
        return resp.json()

    async def refresh_token(self):
        """Refresh token if it expires within 10 minutes."""
        now = datetime.now(timezone.utc)
        if self.account.access_token and self.account.token_expires_at:
            expires = self.account.token_expires_at
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if expires > now + timedelta(minutes=10):
                return  # Still fresh enough
        await self._ensure_token()

    async def get_report(self, report_id: int | str) -> dict:
        headers = await self._headers()
        resp = await self._request_with_retry(
            "GET", f"{AVITO_API_BASE}/autoload/v3/reports/{report_id}", headers=headers,
        )
        resp.raise_for_status()
        return resp.json()

    # Statuses that mean the report is finalized — fees won't change anymore
    _TERMINAL_REPORT_STATUSES = {"completed", "closed", "finished", "done"}

    async def get_report_fees(
        self,
        report_id: int | str,
        page: int = 0,
        per_page: int = 100,
        report_status: str | None = None,
    ) -> dict:
        """Fetch fee data for a report with pagination.

        Cached in-memory by (account_id, report_id). Terminal reports
        (completed/closed/finished/done) get a 24h TTL; otherwise 5min.

        Returns {"fees": [...], "total": int, "report_id": report_id}.
        """
        from app.cache import cache

        cache_key = f"report_fees:{self.account.id}:{report_id}"

        # Cache only the canonical full-report request (no custom paging window)
        cacheable = page == 0 and per_page == 100
        if cacheable:
            hit = await cache.get(cache_key)
            if hit is not None:
                logger.info("get_report_fees cache hit", account_id=self.account.id, report_id=report_id)
                return hit
            logger.info("get_report_fees cache miss", account_id=self.account.id, report_id=report_id)

        headers = await self._headers()
        all_fees: list[dict] = []
        current_page = page
        try:
            while True:
                resp = await self._request_with_retry(
                    "GET",
                    f"{AVITO_API_BASE}/autoload/v2/reports/{report_id}/items/fees",
                    headers=headers,
                    params={"page": current_page, "per_page": per_page},
                )
                resp.raise_for_status()
                data = resp.json()
                fees = data.get("fees") or []
                all_fees.extend(fees)
                meta = data.get("meta", {})
                total_pages = meta.get("pages", 1)
                if current_page + 1 >= total_pages:
                    break
                current_page += 1
        except Exception as e:
            logger.error("get_report_fees failed", report_id=report_id, error=str(e))
            if not all_fees:
                # Don't cache failures — caller may retry
                return {"fees": [], "total": 0, "report_id": report_id}

        result = {
            "fees": all_fees,
            "total": len(all_fees),
            "report_id": report_id,
        }

        if cacheable:
            is_terminal = (
                report_status is not None
                and report_status.lower() in self._TERMINAL_REPORT_STATUSES
            )
            ttl = 24 * 3600 if is_terminal else 5 * 60
            await cache.set(cache_key, result, ttl_seconds=ttl)

        return result

    async def get_ad_ids_by_avito_ids(self, avito_ids: list[int]) -> dict[int, str]:
        """Map Avito IDs to internal ad_ids. Batches by 200."""
        headers = await self._headers()
        result: dict[int, str] = {}
        batch_size = 200
        try:
            for i in range(0, len(avito_ids), batch_size):
                batch = avito_ids[i:i + batch_size]
                resp = await self._request_with_retry(
                    "POST",
                    f"{AVITO_API_BASE}/autoload/v1/items/avito-ids-to-ad-ids",
                    headers=headers,
                    json={"avito_ids": batch},
                )
                resp.raise_for_status()
                data = resp.json()
                items = data.get("items") or []
                for item in items:
                    avito_id = item.get("avito_id")
                    ad_id = item.get("ad_id")
                    if avito_id is not None and ad_id:
                        result[int(avito_id)] = str(ad_id)
        except Exception as e:
            logger.error("get_ad_ids_by_avito_ids failed", error=str(e))
        return result

    async def get_avito_ids_by_ad_ids(self, ad_ids: list[str]) -> dict[str, int]:
        """Map internal ad_ids to Avito IDs. Batches by 200."""
        headers = await self._headers()
        result: dict[str, int] = {}
        batch_size = 200
        try:
            for i in range(0, len(ad_ids), batch_size):
                batch = ad_ids[i:i + batch_size]
                resp = await self._request_with_retry(
                    "POST",
                    f"{AVITO_API_BASE}/autoload/v1/items/ad-ids-to-avito-ids",
                    headers=headers,
                    json={"ad_ids": batch},
                )
                resp.raise_for_status()
                data = resp.json()
                items = data.get("items") or []
                for item in items:
                    ad_id = item.get("ad_id")
                    avito_id = item.get("avito_id")
                    if ad_id and avito_id is not None:
                        result[str(ad_id)] = int(avito_id)
        except Exception as e:
            logger.error("get_avito_ids_by_ad_ids failed", error=str(e))
        return result

    async def get_report_items(self, report_id: int | str, page: int = 0) -> dict:
        headers = await self._headers()
        resp = await self._request_with_retry(
            "GET", f"{AVITO_API_BASE}/autoload/v3/reports/{report_id}/items",
            headers=headers, params={"page": page, "per_page": 100},
        )
        resp.raise_for_status()
        return resp.json()

    async def get_report_items_all(self, report_id: int | str, per_page: int = 200) -> list[dict]:
        """Fetch all items from a report with pagination (v2 API).

        Returns flat list of item dicts with: ad_id, avito_id, url, status, etc.
        """
        headers = await self._headers()
        all_items: list[dict] = []
        page = 0
        while True:
            resp = await self._request_with_retry(
                "GET",
                f"{AVITO_API_BASE}/autoload/v2/reports/{report_id}/items",
                headers=headers,
                params={"page": page, "per_page": per_page},
            )
            resp.raise_for_status()
            data = resp.json()
            items = data.get("items") or []
            all_items.extend(items)
            meta = data.get("meta", {})
            total_pages = meta.get("pages", 1)
            if page + 1 >= total_pages:
                break
            page += 1
        return all_items


async def refresh_all_tokens(db_session) -> dict:
    """Refresh OAuth tokens for all accounts with credentials.

    Called by the scheduler every 50 minutes to keep tokens fresh.
    """
    from sqlalchemy import select as sa_select

    result = await db_session.execute(
        sa_select(Account).where(Account.client_id.isnot(None), Account.client_secret.isnot(None))
    )
    accounts = result.scalars().all()

    refreshed = 0
    errors = 0
    for acc in accounts:
        client = AvitoClient(acc, db_session)
        try:
            await client.refresh_token()
            refreshed += 1
        except Exception as e:
            logger.error("Token refresh failed for %s: %s", acc.name, e)
            errors += 1
        finally:
            await client.close()

    logger.info("Token refresh: %d refreshed, %d errors", refreshed, errors)
    return {"refreshed": refreshed, "errors": errors}
