"""add missing tables: item_stats, listings, listing_images

These tables existed in production (created manually or via
Base.metadata.create_all) but had no Alembic migration.
This caused CI failures: alembic upgrade head would crash on
later migrations that reference item_stats.

Uses IF NOT EXISTS so it's a no-op on prod where tables already exist.
Schema matches pg_dump of production as of 2026-04-18 (v7.4).

Revision ID: b3c4d5e6f8a9
Revises: b3c4d5e6f7a8
Create Date: 2026-04-18 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'b3c4d5e6f8a9'
down_revision: Union[str, None] = 'b3c4d5e6f7a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- listings (must be created before item_stats due to FK) ---
    op.execute("""
        CREATE TABLE IF NOT EXISTS listings (
            id SERIAL PRIMARY KEY,
            product_id INTEGER NOT NULL,
            account_id INTEGER NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'draft',
            scheduled_at TIMESTAMP WITHOUT TIME ZONE,
            published_at TIMESTAMP WITHOUT TIME ZONE,
            avito_id BIGINT,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
            CONSTRAINT listings_product_id_fkey
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
            CONSTRAINT listings_account_id_fkey
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_listings_product_id ON listings (product_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_listings_account_id ON listings (account_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_listings_status ON listings (status)")

    # --- listing_images ---
    op.execute("""
        CREATE TABLE IF NOT EXISTS listing_images (
            id SERIAL PRIMARY KEY,
            listing_id INTEGER NOT NULL,
            file_path VARCHAR(500) NOT NULL,
            "order" INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
            CONSTRAINT listing_images_listing_id_fkey
                FOREIGN KEY (listing_id) REFERENCES listings(id) ON DELETE CASCADE
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_listing_images_listing_id ON listing_images (listing_id)")

    # --- item_stats (depends on listings via FK) ---
    op.execute("""
        CREATE TABLE IF NOT EXISTS item_stats (
            id SERIAL PRIMARY KEY,
            product_id INTEGER NOT NULL,
            avito_id BIGINT,
            views INTEGER NOT NULL DEFAULT 0,
            contacts INTEGER NOT NULL DEFAULT 0,
            favorites INTEGER NOT NULL DEFAULT 0,
            price INTEGER,
            captured_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
            listing_id INTEGER,
            CONSTRAINT item_stats_product_id_fkey
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
            CONSTRAINT item_stats_listing_id_fkey
                FOREIGN KEY (listing_id) REFERENCES listings(id) ON DELETE SET NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_item_stats_product_id ON item_stats (product_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_item_stats_captured ON item_stats (captured_at)")
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_item_stats_product_captured_desc
        ON item_stats (product_id, captured_at DESC)
    """)


def downgrade() -> None:
    # WARNING: destructive on prod — drops tables with all data
    op.execute("DROP TABLE IF EXISTS listing_images")
    op.execute("DROP TABLE IF EXISTS item_stats")
    op.execute("DROP TABLE IF EXISTS listings")
