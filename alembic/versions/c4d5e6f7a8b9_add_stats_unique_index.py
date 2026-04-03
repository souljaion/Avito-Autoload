"""add unique index for stats upsert

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-04-02 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c4d5e6f7a8b9'
down_revision: Union[str, None] = 'b3c4d5e6f7a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Unique index on (product_id, date(captured_at)) for upsert
    op.execute("""
        CREATE UNIQUE INDEX uq_item_stats_product_date
        ON item_stats (product_id, (captured_at::date))
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_item_stats_product_date")
