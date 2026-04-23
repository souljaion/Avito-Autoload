"""add color_manufacturer to products

Revision ID: c1a2b3d4e5f6
Revises: b8744625def2
Create Date: 2026-04-23 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c1a2b3d4e5f6'
down_revision: Union[str, None] = 'b8744625def2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('products', sa.Column('color_manufacturer', sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column('products', 'color_manufacturer')
