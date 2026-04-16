"""One-off: backfill brand/goods_type/size/color/image_url for imported products
that already have an avito_id but were created with the minimal Pass 3 schema.

Usage:
  python3 scripts/backfill_imported_details.py             # all candidates
  python3 scripts/backfill_imported_details.py --limit 5   # first N (smoke test)

Note: the Avito Items API in our autoload OAuth scope only returns
{address, category, id, price, status, title, url} — no brand, params, or
images. Backfilling these requires either web scraping the public ad URL
or manual data entry; this script can fill `category` and `image_url` from
whatever the API does provide, but expect mostly empty results until those
data sources are added.
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Make the app package importable when running from project root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.db import async_session
from app.models.account import Account
from app.models.product import Product
from app.services.avito_client import AvitoClient
from app.services.autoload_sync import _extract_item_details

REQUEST_DELAY_SEC = 0.2  # gentle on Avito API


async def _backfill_account(account: Account, products: list[Product]) -> dict:
    """Process all imported products for a single account.

    Returns counters dict: {updated, empty, errors}.
    """
    counters = {"updated": 0, "empty": 0, "errors": 0}
    total = len(products)
    name_w = max(20, len(account.name))

    async with async_session() as db:
        client = AvitoClient(account, db)
        try:
            for idx, raw_p in enumerate(products, 1):
                # Re-fetch in this session to bind for UPDATE
                p = await db.get(Product, raw_p.id)
                if p is None:
                    counters["errors"] += 1
                    print(f"  [{idx}/{total}] {account.name:<{name_w}} — id={raw_p.id} → пропал из БД ✗")
                    continue

                title_short = (p.title or "")[:50]
                try:
                    extracted = await _extract_item_details(client, p.avito_id)
                except Exception as e:
                    counters["errors"] += 1
                    print(f"  [{idx}/{total}] {account.name:<{name_w}} — {title_short} → EXC {e} ✗")
                    await asyncio.sleep(REQUEST_DELAY_SEC)
                    continue

                if not extracted:
                    counters["empty"] += 1
                    print(f"  [{idx}/{total}] {account.name:<{name_w}} — {title_short} → пустой ответ API ✗")
                    await asyncio.sleep(REQUEST_DELAY_SEC)
                    continue

                # Apply updates
                touched = []
                for col, val in extracted.items():
                    if not val:
                        continue
                    current = getattr(p, col, None)
                    if not current:
                        setattr(p, col, val)
                        touched.append(f"{col}={val[:20]}")
                if touched:
                    try:
                        await db.commit()
                        counters["updated"] += 1
                        print(f"  [{idx}/{total}] {account.name:<{name_w}} — {title_short} → {', '.join(touched)} ✓")
                    except Exception as e:
                        await db.rollback()
                        counters["errors"] += 1
                        print(f"  [{idx}/{total}] {account.name:<{name_w}} — {title_short} → COMMIT FAIL: {e} ✗")
                else:
                    counters["empty"] += 1
                    print(f"  [{idx}/{total}] {account.name:<{name_w}} — {title_short} → ничего не извлечено ✗")

                await asyncio.sleep(REQUEST_DELAY_SEC)
        finally:
            await client.close()

    return counters


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None,
                        help="Process at most N products (smoke test)")
    parser.add_argument("--account", type=int, default=None,
                        help="Restrict to a single account_id")
    args = parser.parse_args()

    print("=" * 70)
    print("Backfill imported product details from Avito Items API")
    print("=" * 70)

    # 1. Find candidates grouped by account
    async with async_session() as db:
        # Pick imported products with avito_id. We try to fill anything we can
        # via the Items API (currently only `category` — Avito's autoload scope
        # doesn't expose brand/params/images). Skip products that already have
        # both `category` AND `brand` (nothing more to gain).
        from sqlalchemy import and_, or_
        stmt = select(Product, Account).join(
            Account, Account.id == Product.account_id
        ).where(
            Product.status == "imported",
            Product.avito_id.isnot(None),
            or_(Product.brand.is_(None), Product.category.is_(None)),
        ).order_by(Product.account_id, Product.id)
        if args.account is not None:
            stmt = stmt.where(Product.account_id == args.account)
        if args.limit:
            stmt = stmt.limit(args.limit)
        result = await db.execute(stmt)
        rows = result.all()

    by_account: dict[int, tuple[Account, list[Product]]] = {}
    for product, account in rows:
        if account.id not in by_account:
            by_account[account.id] = (account, [])
        by_account[account.id][1].append(product)

    if not by_account:
        print("Нет товаров для обновления.")
        return

    total_candidates = sum(len(p) for _, p in by_account.values())
    print(f"Кандидатов на обновление: {total_candidates} в {len(by_account)} аккаунтах\n")

    # 2. Process per account
    grand_total = {"updated": 0, "empty": 0, "errors": 0}
    for account, products in by_account.values():
        print(f"\n--- {account.name} (id={account.id}): {len(products)} товаров ---")
        counters = await _backfill_account(account, products)
        for k in grand_total:
            grand_total[k] += counters[k]

    # 3. Summary
    print()
    print("=" * 70)
    print("ИТОГ")
    print("=" * 70)
    print(f"  Обновлено:        {grand_total['updated']}")
    print(f"  Пустой ответ API: {grand_total['empty']}")
    print(f"  Ошибки:           {grand_total['errors']}")
    print(f"  Всего обработано: {sum(grand_total.values())}")


if __name__ == "__main__":
    asyncio.run(main())
