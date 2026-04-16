"""Import avito_ids from the actual XML feed Avito polls.

Workflow:
  1. GET /autoload/v1/profile → discover feed URL (feeds_data[0].url, fallback upload_url)
  2. GET that URL with Bearer token → XML bytes
  3. Parse <Ad> elements: AvitoId / Id / Title / Status
  4. For each non-Removed ad:
     a. Skip if (account_id, avito_id) already in DB
     b. Try title match (case-insensitive, whitespace-collapsed) on
        products with avito_id IS NULL → fill avito_id (matched)
     c. Otherwise create new imported product with avito_id (created)

This bypasses the Items API and avoids fuzzy guessing — the feed is the
source of truth for what Avito has under our autoload.
"""

from datetime import datetime, timezone

import httpx
import structlog
from lxml import etree
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.product import Product
from app.services.avito_client import AvitoClient

logger = structlog.get_logger(__name__)


def _norm(s: str | None) -> str:
    """Normalize title for matching: trim + collapse whitespace + lowercase."""
    return " ".join((s or "").split()).lower()


def _extract_feed_url(profile: dict) -> str | None:
    """Pull feed URL from profile, preferring feeds_data over deprecated upload_url."""
    feeds_data = profile.get("feeds_data") or []
    if feeds_data:
        # feeds_data is a list of {name, url}; take the first non-empty url
        for entry in feeds_data:
            url = (entry or {}).get("url")
            if url:
                return url
    return profile.get("upload_url") or None


def _parse_feed_xml(xml_bytes: bytes) -> list[dict]:
    """Parse XML feed → list of {avito_id, ad_id, title, status}.

    Tolerates malformed entries: bad <Ad> blocks are skipped, not raised.
    """
    try:
        root = etree.fromstring(xml_bytes)
    except etree.XMLSyntaxError as e:
        raise ValueError(f"Invalid XML feed: {e}") from e

    ads: list[dict] = []
    for ad in root.iter("Ad"):
        def _text(tag: str) -> str | None:
            el = ad.find(tag)
            return el.text.strip() if (el is not None and el.text) else None

        avito_id_str = _text("AvitoId")
        avito_id: int | None = None
        if avito_id_str:
            try:
                avito_id = int(avito_id_str)
            except ValueError:
                avito_id = None

        ads.append({
            "avito_id": avito_id,
            "ad_id": _text("Id"),
            "title": _text("Title") or "",
            "status": _text("Status"),
        })
    return ads


async def sync_avito_ids_from_feed(
    account_id: int, db: AsyncSession, client: AvitoClient | None = None,
) -> dict:
    """Download Avito's current feed and import avito_ids into our DB."""
    account = await db.get(Account, account_id)
    if not account:
        return {
            "matched": 0, "created": 0, "skipped": 0, "total_in_feed": 0,
            "error": "Account not found",
        }

    own_client = client is None
    if own_client:
        client = AvitoClient(account, db)

    try:
        # 1. Profile → feed URL
        try:
            profile = await client.get_autoload_profile()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.warning("feed_importer.profile_not_found", account_id=account_id)
                return {
                    "matched": 0, "created": 0, "skipped": 0, "total_in_feed": 0,
                    "error": "profile not found",
                }
            logger.exception("feed_importer.profile_http_error", account_id=account_id)
            return {
                "matched": 0, "created": 0, "skipped": 0, "total_in_feed": 0,
                "error": f"profile fetch failed: HTTP {e.response.status_code}",
            }

        feed_url = _extract_feed_url(profile)
        if not feed_url:
            logger.warning("feed_importer.no_feed_url", account_id=account_id, profile_keys=list(profile.keys()))
            return {
                "matched": 0, "created": 0, "skipped": 0, "total_in_feed": 0,
                "error": "no feed url",
            }

        # 2. Download XML — use Bearer token in case the URL is behind Avito auth
        headers = await client._headers()
        try:
            async with httpx.AsyncClient(timeout=60.0) as http:
                resp = await http.get(feed_url, headers={"Authorization": headers["Authorization"]})
                resp.raise_for_status()
                xml_bytes = resp.content
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            logger.exception("feed_importer.download_failed", account_id=account_id, feed_url=feed_url)
            return {
                "matched": 0, "created": 0, "skipped": 0, "total_in_feed": 0,
                "error": f"feed download failed: {e}",
            }

        # 3. Parse
        try:
            ads = _parse_feed_xml(xml_bytes)
        except ValueError as e:
            logger.exception("feed_importer.parse_failed", account_id=account_id)
            return {
                "matched": 0, "created": 0, "skipped": 0, "total_in_feed": 0,
                "error": str(e),
            }

        # 4. Snapshot existing per-account state
        existing_by_avito_result = await db.execute(
            select(Product.avito_id).where(
                Product.account_id == account_id,
                Product.avito_id.isnot(None),
            )
        )
        existing_avito_ids: set[int] = {row[0] for row in existing_by_avito_result.all()}

        null_products_result = await db.execute(
            select(Product).where(
                Product.account_id == account_id,
                Product.avito_id.is_(None),
            )
        )
        null_products = list(null_products_result.scalars().all())
        by_norm_title: dict[str, Product] = {}
        for p in null_products:
            n = _norm(p.title)
            if n and n not in by_norm_title:
                by_norm_title[n] = p

        # Global avito_ids snapshot — avoid cross-account collisions on insert
        global_avito_result = await db.execute(
            select(Product.avito_id).where(Product.avito_id.isnot(None))
        )
        global_avito_ids: set[int] = {row[0] for row in global_avito_result.all()}

        matched = 0
        created = 0
        skipped = 0
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        for ad in ads:
            status = (ad.get("status") or "").lower()
            if status == "removed":
                skipped += 1
                continue

            avito_id = ad.get("avito_id")
            if not avito_id:
                # Entry has no <AvitoId> — Avito hasn't assigned one yet, nothing to import
                skipped += 1
                continue

            # (a) Already known under this account
            if avito_id in existing_avito_ids:
                skipped += 1
                continue

            # Avoid global avito_id collisions (held by another account)
            if avito_id in global_avito_ids:
                logger.warning(
                    "feed_importer.avito_id_belongs_to_other_account",
                    account_id=account_id, avito_id=avito_id,
                )
                skipped += 1
                continue

            # (b) Title match against NULL-avito_id products
            n = _norm(ad.get("title"))
            target = by_norm_title.get(n) if n else None
            if target is not None:
                target.avito_id = avito_id
                existing_avito_ids.add(avito_id)
                global_avito_ids.add(avito_id)
                del by_norm_title[n]
                matched += 1
                logger.info(
                    "feed_importer.matched",
                    account_id=account_id,
                    avito_id=avito_id,
                    product_id=target.id,
                    title=(ad.get("title") or "")[:80],
                )
                continue

            # (c) Create new imported
            title = ad.get("title") or f"[Авито] {avito_id}"
            product = Product(
                avito_id=avito_id,
                account_id=account_id,
                title=title[:255],
                status="imported",
                published_at=now,
            )
            db.add(product)
            existing_avito_ids.add(avito_id)
            global_avito_ids.add(avito_id)
            created += 1
            logger.info(
                "feed_importer.created",
                account_id=account_id,
                avito_id=avito_id,
                title=title[:80],
            )

        if matched or created:
            await db.commit()

        result = {
            "matched": matched,
            "created": created,
            "skipped": skipped,
            "total_in_feed": len(ads),
            "error": None,
        }
        logger.info(
            "feed_importer.done",
            account=account.name, account_id=account_id, **result,
        )
        return result

    except Exception as e:
        await db.rollback()
        logger.exception("feed_importer.failed", account_id=account_id)
        return {
            "matched": 0, "created": 0, "skipped": 0, "total_in_feed": 0,
            "error": str(e),
        }
    finally:
        if own_client:
            await client.close()
