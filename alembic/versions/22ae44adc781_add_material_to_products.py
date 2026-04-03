"""add_material_to_products

Revision ID: 22ae44adc781
Revises: 83f8cdf7b825
Create Date: 2026-03-31 18:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '22ae44adc781'
down_revision: Union[str, None] = '83f8cdf7b825'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('products', sa.Column('material', sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column('products', 'material')
