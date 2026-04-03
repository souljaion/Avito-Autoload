"""add_goods_type_to_products

Revision ID: d929ae95352d
Revises: 67e6e28d1dd4
Create Date: 2026-03-31 16:59:55.544965

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd929ae95352d'
down_revision: Union[str, None] = '67e6e28d1dd4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('products', sa.Column('goods_type', sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column('products', 'goods_type')
