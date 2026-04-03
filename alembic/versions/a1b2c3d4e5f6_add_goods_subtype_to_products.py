"""add_goods_subtype_to_products

Revision ID: a1b2c3d4e5f6
Revises: 22ae44adc781
Create Date: 2026-03-31 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '22ae44adc781'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('products', sa.Column('goods_subtype', sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column('products', 'goods_subtype')
