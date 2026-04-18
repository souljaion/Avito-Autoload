"""
One-time migration: copy account-level description templates into the
standalone description_templates table.

Usage:
    cd /home/claude2/avito-autoload
    source venv/bin/activate
    python scripts/migrate_account_templates.py

Templates are named "{account_name} — импорт". Uses ON CONFLICT (name)
DO NOTHING for idempotency — safe to run multiple times.
"""

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

from app.config import settings


async def main():
    engine = create_async_engine(str(settings.DATABASE_URL))

    migrated = 0
    skipped = 0

    async with engine.begin() as conn:
        # Fetch account templates with non-empty body
        rows = (await conn.execute(text(
            "SELECT a.name, t.description_template "
            "FROM account_description_templates t "
            "JOIN accounts a ON a.id = t.account_id "
            "WHERE t.description_template IS NOT NULL "
            "AND t.description_template != ''"
        ))).all()

        for account_name, body in rows:
            name = f"{account_name} — импорт"
            result = await conn.execute(text(
                "INSERT INTO description_templates (name, body, created_at, updated_at) "
                "VALUES (:name, :body, now(), now()) "
                "ON CONFLICT (name) DO NOTHING "
                "RETURNING id"
            ), {"name": name, "body": body})

            if result.scalar():
                migrated += 1
                print(f"  + {name}")
            else:
                skipped += 1
                print(f"  = {name} (already exists)")

    await engine.dispose()
    print(f"\nMigrated {migrated} templates, skipped {skipped} duplicates")


if __name__ == "__main__":
    asyncio.run(main())
