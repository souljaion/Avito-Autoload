"""add performance indexes

Revision ID: d4e5f6a7b8c0
Revises: c3d4e5f6a7b9
Create Date: 2026-04-14 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'd4e5f6a7b8c0'
down_revision: Union[str, None] = 'c3d4e5f6a7b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # item_stats: composite index for analytics delta queries
    op.execute("""
        CREATE INDEX ix_item_stats_product_captured_desc
        ON item_stats (product_id, captured_at DESC)
    """)

    # products: composite index for listing/feed queries
    op.create_index(
        "ix_products_account_id_status",
        "products",
        ["account_id", "status"],
    )

    # products: partial index for cleanup_removed job
    op.execute("""
        CREATE INDEX ix_products_removed_at_partial
        ON products (removed_at)
        WHERE removed_at IS NOT NULL
    """)

    # autoload_report_items: composite index for filtering declined/blocked
    op.create_index(
        "ix_autoload_report_items_report_status",
        "autoload_report_items",
        ["report_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_autoload_report_items_report_status", table_name="autoload_report_items")
    op.execute("DROP INDEX IF EXISTS ix_products_removed_at_partial")
    op.drop_index("ix_products_account_id_status", table_name="products")
    op.execute("DROP INDEX IF EXISTS ix_item_stats_product_captured_desc")
