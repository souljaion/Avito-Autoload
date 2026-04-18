"""add missing columns to products, accounts, feed_exports

These columns existed in production (added manually) but had no
Alembic migration, causing schema mismatch in CI fresh environments.

Uses ADD COLUMN IF NOT EXISTS (Postgres 9.6+) so it's a no-op on prod
where columns already exist. Constraints/FKs use Python-level existence
checks because asyncpg doesn't support PL/pgSQL DO blocks.

Revision ID: a2b3c4d5e6f0
Revises: 311820dce3e8
Create Date: 2026-04-18 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a2b3c4d5e6f0'
down_revision: Union[str, None] = '311820dce3e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _constraint_exists(conn, name: str) -> bool:
    result = conn.execute(
        sa.text("SELECT 1 FROM pg_constraint WHERE conname = :name"),
        {"name": name},
    )
    return result.scalar() is not None


def upgrade() -> None:
    # --- products: 5 missing columns ---
    op.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS avito_id BIGINT")
    op.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS scheduled_at TIMESTAMP WITHOUT TIME ZONE")
    op.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS published_at TIMESTAMP WITHOUT TIME ZONE")
    op.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS scheduled_account_id INTEGER")
    op.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS image_url VARCHAR(500)")

    # products: unique constraint + indexes + FK (idempotent)
    conn = op.get_bind()
    if not _constraint_exists(conn, "products_avito_id_key"):
        op.execute("ALTER TABLE products ADD CONSTRAINT products_avito_id_key UNIQUE (avito_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_products_avito_id ON products (avito_id) WHERE avito_id IS NOT NULL")
    op.execute("CREATE INDEX IF NOT EXISTS ix_products_scheduled ON products (scheduled_at) WHERE status = 'scheduled'")
    if not _constraint_exists(conn, "products_scheduled_account_id_fkey"):
        op.execute(
            "ALTER TABLE products ADD CONSTRAINT products_scheduled_account_id_fkey "
            "FOREIGN KEY (scheduled_account_id) REFERENCES accounts(id) ON DELETE SET NULL"
        )

    # --- accounts: 1 missing column ---
    op.execute("ALTER TABLE accounts ADD COLUMN IF NOT EXISTS avito_user_id BIGINT")

    # --- feed_exports: 2 missing columns ---
    op.execute("ALTER TABLE feed_exports ADD COLUMN IF NOT EXISTS uploaded_at TIMESTAMPTZ")
    op.execute("ALTER TABLE feed_exports ADD COLUMN IF NOT EXISTS upload_response JSONB")


def downgrade() -> None:
    # WARNING: destructive — drops columns with all data
    op.execute("ALTER TABLE feed_exports DROP COLUMN IF EXISTS upload_response")
    op.execute("ALTER TABLE feed_exports DROP COLUMN IF EXISTS uploaded_at")
    op.execute("ALTER TABLE accounts DROP COLUMN IF EXISTS avito_user_id")
    op.execute("ALTER TABLE products DROP CONSTRAINT IF EXISTS products_scheduled_account_id_fkey")
    op.execute("DROP INDEX IF EXISTS ix_products_scheduled")
    op.execute("DROP INDEX IF EXISTS ix_products_avito_id")
    op.execute("ALTER TABLE products DROP CONSTRAINT IF EXISTS products_avito_id_key")
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS image_url")
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS scheduled_account_id")
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS published_at")
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS scheduled_at")
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS avito_id")
