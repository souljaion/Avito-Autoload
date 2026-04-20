"""Sync existing autoload ads from Avito into the products table."""

from datetime import datetime, timezone

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.product import Product
from app.services.avito_client import AvitoClient

logger = structlog.get_logger(__name__)

# Suppress repeated 404 warnings for dead reports API (one per account per process)
_reports_api_404_logged: dict[int, bool] = {}


# Map Avito param names → product columns. Match by case-insensitive substring
# because Avito's params labels vary slightly across categories.
_PARAM_PATTERNS = {
    "goods_type":     ["вид товара", "вид одежды", "вид обуви"],
    "goods_subtype":  ["подвид"],
    "size":           ["размер"],
    "color":          ["цвет"],
    "brand":          ["бренд", "производитель"],
}


def _match_param(param_name: str, patterns: list[str]) -> bool:
    n = (param_name or "").lower()
    return any(p in n for p in patterns)


async def _extract_item_details(client: AvitoClient, avito_id: int) -> dict:
    """Best-effort backfill: pull item from Items API and map available fields.

    NOTE: under the autoload OAuth scope, `/core/v1/items?ids=N` returns a
    LIMITED set of fields: {address, category{id,name}, id, price, status,
    title, url}. Brand, params and images are NOT available — those columns
    can only be filled by other means (web scraping public ad URL or manual
    data entry).

    Returns a dict with whichever known columns could be filled.
    """
    try:
        details = await client.get_item_details(avito_id)
    except Exception as e:
        logger.warning("autoload_sync.pass3_details_failed",
                       avito_id=avito_id, error=str(e))
        return {}
    if not details:
        return {}

    out: dict = {}

    # category.name → product.category (top-level Avito category)
    cat = details.get("category")
    if isinstance(cat, dict):
        cat_name = cat.get("name")
        if isinstance(cat_name, str) and cat_name.strip():
            out["category"] = cat_name.strip()[:255]

    # If the API ever starts exposing more fields (params/images/brand),
    # the helpers below will pick them up automatically.
    brand = details.get("brand")
    if isinstance(brand, str) and brand.strip():
        out["brand"] = brand.strip()[:255]

    params = details.get("params") or []
    if isinstance(params, dict):
        params = [{"name": k, "value": v} for k, v in params.items()]
    for p in params:
        if not isinstance(p, dict):
            continue
        pname = p.get("name") or ""
        pval = p.get("value")
        if pval is None or pval == "":
            continue
        pval_s = str(pval).strip()
        if not pval_s:
            continue
        for col, patterns in _PARAM_PATTERNS.items():
            if col in out:
                continue
            if _match_param(pname, patterns):
                out[col] = pval_s[:255]
                break

    images = details.get("images") or []
    if isinstance(images, list) and images:
        first = images[0]
        if isinstance(first, dict):
            url = first.get("url") or first.get("href")
            if isinstance(url, str) and url.startswith("http"):
                out["image_url"] = url[:500]

    if out:
        logger.info("autoload_sync.pass3_details_fetched",
                    avito_id=avito_id, filled=list(out.keys()))
    return out


async def sync_ads_from_avito(
    account_id: int, db: AsyncSession, client: AvitoClient | None = None,
) -> dict:
    """Sync applied ads from the latest Avito autoload report into products.

    Returns {"synced": N, "created": N, "skipped": N, "error": str|None}.
    """
    account = await db.get(Account, account_id)
    if not account:
        return {
            "synced": 0, "created": 0, "skipped": 0,
            "pass3_matched": 0, "pass3_created": 0,
            "error": "Account not found",
        }

    own_client = client is None
    if own_client:
        client = AvitoClient(account, db)

    try:
        # All avito_ids across all accounts to avoid dupes (needed by all passes)
        all_avito_result = await db.execute(
            select(Product.avito_id).where(Product.avito_id.isnot(None))
        )
        all_avito_ids = {row[0] for row in all_avito_result.all()}

        created = 0
        synced = 0
        skipped = 0
        report_id = None
        items: list = []

        # ── Pass 1: Reports API — sync applied ads from autoload report ──
        try:
            reports_data = await client.get_reports()
            reports = reports_data.get("reports") or []

            if reports:
                report_id = reports[0].get("id")

            if report_id:
                items = await client.get_report_items_all(report_id)

                existing_result = await db.execute(
                    select(Product).where(
                        Product.account_id == account_id,
                        Product.avito_id.isnot(None),
                    )
                )
                existing_by_avito_id = {p.avito_id: p for p in existing_result.scalars().all()}

                sku_result = await db.execute(
                    select(Product).where(
                        Product.account_id == account_id,
                        Product.sku.isnot(None),
                    )
                )
                existing_by_sku = {p.sku: p for p in sku_result.scalars().all()}

                for item in items:
                    try:
                        status = item.get("status", "")
                        if status != "applied":
                            skipped += 1
                            continue

                        avito_id = item.get("avito_id")
                        ad_id = str(item.get("ad_id", "")) or None

                        if not avito_id:
                            skipped += 1
                            continue

                        avito_id = int(avito_id)

                        if avito_id in existing_by_avito_id:
                            synced += 1
                            continue

                        if ad_id and ad_id in existing_by_sku:
                            product = existing_by_sku[ad_id]
                            if product.avito_id is None and avito_id not in all_avito_ids:
                                product.avito_id = avito_id
                                all_avito_ids.add(avito_id)
                                synced += 1
                            else:
                                skipped += 1
                            continue

                        if avito_id in all_avito_ids:
                            skipped += 1
                            continue

                        product = Product(
                            avito_id=avito_id,
                            sku=ad_id,
                            account_id=account_id,
                            status="imported",
                            title=f"[Авито] {avito_id}",
                            published_at=datetime.now(timezone.utc).replace(tzinfo=None),
                        )
                        db.add(product)
                        all_avito_ids.add(avito_id)
                        created += 1

                    except Exception as e:
                        logger.warning("autoload_sync.item_error", avito_id=item.get("avito_id"), error=str(e))
                        skipped += 1

                await db.commit()

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                if not _reports_api_404_logged.get(account_id):
                    logger.warning(
                        "autoload_sync.reports_api_unavailable",
                        account_id=account_id,
                        url=str(e.request.url),
                    )
                    _reports_api_404_logged[account_id] = True
                # Pass 1 skipped — continue to Pass 2/3
            else:
                raise

        # ── Pass 2: Items API — fill avito_id for products with NULL ──
        avito_ids_filled = 0
        api_items: list[dict] = []
        try:
            api_items = await client.get_all_items()
            if api_items:
                # Load products with NULL avito_id for this account
                null_avito_result = await db.execute(
                    select(Product).where(
                        Product.account_id == account_id,
                        Product.avito_id.is_(None),
                    )
                )
                null_avito_products = null_avito_result.scalars().all()
                # Index by exact title for O(1) lookup
                by_title: dict[str, Product] = {}
                for p in null_avito_products:
                    if p.title and p.title not in by_title:
                        by_title[p.title] = p

                for api_item in api_items:
                    avito_id = api_item.get("id")
                    title = api_item.get("title", "")
                    if not avito_id or not title:
                        continue
                    avito_id = int(avito_id)
                    # Skip if this avito_id is already used
                    if avito_id in all_avito_ids:
                        continue
                    # Exact title match only
                    product = by_title.get(title)
                    if product and product.avito_id is None:
                        product.avito_id = avito_id
                        all_avito_ids.add(avito_id)
                        # Remove from index so we don't match again
                        del by_title[title]
                        avito_ids_filled += 1

                if avito_ids_filled:
                    await db.commit()
        except Exception as e:
            logger.warning("autoload_sync.pass2_failed", account_id=account_id, error=str(e))

        # ── Pass 3: Items API — match-then-create for ads not in DB ──
        # For each Avito ad whose avito_id we don't have:
        #   1. Try fuzzy title match against existing imported products with NULL avito_id
        #      → fill avito_id (pass3_matched)
        #   2. Otherwise create a new imported product (pass3_created)
        pass3_matched = 0
        pass3_created = 0
        try:
            if api_items:
                # Snapshot per-account avito_ids (after Pass 1+2)
                acc_avito_result = await db.execute(
                    select(Product.avito_id).where(
                        Product.account_id == account_id,
                        Product.avito_id.isnot(None),
                    )
                )
                acc_avito_ids = {row[0] for row in acc_avito_result.all()}

                # Reload NULL-avito_id products for this account (Pass 2 may have
                # consumed some; fresh read is cheap and avoids stale state).
                null_avito_result_p3 = await db.execute(
                    select(Product).where(
                        Product.account_id == account_id,
                        Product.avito_id.is_(None),
                    )
                )
                null_avito_products_p3 = list(null_avito_result_p3.scalars().all())

                # Build two title indexes for fuzzy matching:
                # 1) exact normalized (lowercase + collapsed whitespace)
                # 2) first 50 chars of normalized title — prefix fallback
                def _norm(s: str) -> str:
                    return " ".join((s or "").split()).lower()

                by_norm: dict[str, Product] = {}
                by_prefix: dict[str, Product] = {}
                for p in null_avito_products_p3:
                    n = _norm(p.title or "")
                    if not n:
                        continue
                    by_norm.setdefault(n, p)
                    by_prefix.setdefault(n[:50], p)

                def _claim(product: Product, avito_id: int) -> None:
                    """Drop product from both indexes once its avito_id is filled."""
                    n = _norm(product.title or "")
                    by_norm.pop(n, None)
                    by_prefix.pop(n[:50], None)

                now = datetime.now(timezone.utc).replace(tzinfo=None)

                for api_item in api_items:
                    raw_id = api_item.get("id")
                    if not raw_id:
                        continue
                    try:
                        avito_id = int(raw_id)
                    except (TypeError, ValueError):
                        continue
                    if avito_id in acc_avito_ids:
                        continue
                    # Avoid global avito_id collisions (another account holds it)
                    if avito_id in all_avito_ids:
                        continue

                    raw_title = api_item.get("title") or ""
                    norm_title = _norm(raw_title)

                    # Step 1 — fuzzy title match
                    matched: Product | None = None
                    if norm_title:
                        matched = by_norm.get(norm_title)
                        if matched is None:
                            matched = by_prefix.get(norm_title[:50])

                    if matched is not None:
                        matched.avito_id = avito_id
                        all_avito_ids.add(avito_id)
                        acc_avito_ids.add(avito_id)
                        _claim(matched, avito_id)
                        pass3_matched += 1
                        logger.info(
                            "autoload_sync.pass3_matched",
                            account_id=account_id,
                            avito_id=avito_id,
                            product_id=matched.id,
                            title=raw_title[:80],
                        )
                        continue

                    # Step 2 — create new imported product, enrich via item details
                    title = raw_title or f"[Авито] {avito_id}"
                    price = api_item.get("price")
                    try:
                        price_val = int(price) if price is not None else None
                    except (TypeError, ValueError):
                        price_val = None

                    # Best-effort backfill: pull full item from Items API.
                    # Only for NEW products in Pass 3 — keeps API call count bounded.
                    extra_fields = await _extract_item_details(client, avito_id)

                    product = Product(
                        avito_id=avito_id,
                        account_id=account_id,
                        title=title[:255],
                        price=price_val,
                        status="imported",
                        published_at=now,
                        brand=extra_fields.get("brand"),
                        goods_type=extra_fields.get("goods_type"),
                        goods_subtype=extra_fields.get("goods_subtype"),
                        size=extra_fields.get("size"),
                        color=extra_fields.get("color"),
                        image_url=extra_fields.get("image_url"),
                    )
                    db.add(product)
                    all_avito_ids.add(avito_id)
                    acc_avito_ids.add(avito_id)
                    pass3_created += 1
                    logger.info(
                        "autoload_sync.pass3_created",
                        account_id=account_id,
                        avito_id=avito_id,
                        title=title[:80],
                        details_filled=sum(1 for v in extra_fields.values() if v),
                    )

                if pass3_matched or pass3_created:
                    await db.commit()
        except Exception as e:
            await db.rollback()
            logger.warning("autoload_sync.pass3_failed", account_id=account_id, error=str(e))

        logger.info(
            "autoload_sync.done",
            account=account.name,
            account_id=account_id,
            report_id=report_id,
            created=created,
            synced=synced,
            skipped=skipped,
            avito_ids_filled=avito_ids_filled,
            pass3_matched=pass3_matched,
            pass3_created=pass3_created,
            total_items=len(items),
        )
        return {
            "synced": synced, "created": created, "skipped": skipped,
            "avito_ids_filled": avito_ids_filled,
            "pass3_matched": pass3_matched,
            "pass3_created": pass3_created,
            "error": None,
        }

    except Exception as e:
        await db.rollback()
        logger.exception("autoload_sync.failed", account_id=account_id, error=str(e))
        return {
            "synced": 0, "created": 0, "skipped": 0,
            "pass3_matched": 0, "pass3_created": 0,
            "error": str(e),
        }
    finally:
        if own_client:
            await client.close()
