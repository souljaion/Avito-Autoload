"""add_feed_ad_id_to_products

Revision ID: b8744625def2
Revises: 5ae9f0bf8896
Create Date: 2026-04-22 13:41:08.681856

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8744625def2'
down_revision: Union[str, None] = '5ae9f0bf8896'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("products", sa.Column("feed_ad_id", sa.String(100), nullable=True))
    op.create_index("ix_products_feed_ad_id", "products", ["feed_ad_id"])


def downgrade() -> None:
    op.drop_index("ix_products_feed_ad_id", table_name="products")
    op.drop_column("products", "feed_ad_id")
