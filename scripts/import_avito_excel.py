"""CLI runner: import Avito Excel exports for one or all accounts.

Reads files from uploads/avito_export/{account_id}.xlsx and delegates the
actual work to app/services/excel_importer.py.

Usage:
    python3 scripts/import_avito_excel.py            # all accounts found
    python3 scripts/import_avito_excel.py --account 3
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Make app/ importable when running directly
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.db import async_session
from app.models.account import Account
from app.services.excel_importer import import_avito_excel, InvalidExcelError


UPLOAD_DIR = Path("uploads/avito_export")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", type=int, default=None,
                        help="Process only this account_id")
    args = parser.parse_args()

    if not UPLOAD_DIR.is_dir():
        print(f"Upload dir not found: {UPLOAD_DIR}")
        return

    files: list[tuple[int, Path]] = []
    for p in sorted(UPLOAD_DIR.glob("*.xlsx")):
        try:
            aid = int(p.stem)
        except ValueError:
            continue
        if args.account is not None and aid != args.account:
            continue
        files.append((aid, p))

    if not files:
        print("No matching .xlsx files found.")
        return

    print(f"Files to process: {[(a, p.name) for a, p in files]}")

    # Pre-fetch account names for the summary
    async with async_session() as db:
        rows = await db.execute(select(Account))
        names = {a.id: a.name for a in rows.scalars().all()}

    summary: dict[int, tuple[str, dict]] = {}
    for aid, path in files:
        name = names.get(aid, f"id={aid}")
        print(f"\n=== {name} (id={aid}, file={path.name}) ===")
        async with async_session() as db:
            try:
                counters = await import_avito_excel(aid, path.read_bytes(), db)
            except InvalidExcelError as e:
                print(f"  ✗ {e}")
                counters = {"updated": 0, "created": 0, "photos": 0, "skipped": 0, "errors": 1}
        summary[aid] = (name, counters)
        print(f"  updated={counters['updated']} created={counters['created']} "
              f"photos={counters['photos']} skipped={counters['skipped']} errors={counters['errors']}")

    print()
    print("=" * 78)
    print(f"{'Аккаунт':<16} {'Обновлено':>10} {'Создано':>9} {'Фото':>7} {'Skipped':>9} {'Ошибки':>8}")
    print("-" * 78)
    grand = {"updated": 0, "created": 0, "photos": 0, "skipped": 0, "errors": 0}
    for aid, (name, c) in summary.items():
        print(f"{name:<16} {c['updated']:>10} {c['created']:>9} {c['photos']:>7} {c['skipped']:>9} {c['errors']:>8}")
        for k in grand:
            grand[k] += c[k]
    print("-" * 78)
    print(f"{'ИТОГО':<16} {grand['updated']:>10} {grand['created']:>9} {grand['photos']:>7} {grand['skipped']:>9} {grand['errors']:>8}")


if __name__ == "__main__":
    asyncio.run(main())
