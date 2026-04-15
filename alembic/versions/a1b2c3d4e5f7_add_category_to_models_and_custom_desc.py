"""add category fields to models and use_custom_description to products

Revision ID: a1b2c3d4e5f7
Revises: f7e8d9c0b1a2
Create Date: 2026-04-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f7'
down_revision: Union[str, None] = 'f7e8d9c0b1a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('models', sa.Column('category', sa.String(length=100), nullable=True))
    op.add_column('models', sa.Column('subcategory', sa.String(length=100), nullable=True))
    op.add_column('models', sa.Column('goods_type', sa.String(length=100), nullable=True))
    op.add_column('models', sa.Column('goods_subtype', sa.String(length=100), nullable=True))
    op.add_column('products', sa.Column('use_custom_description', sa.Boolean(), server_default='false', nullable=False))


def downgrade() -> None:
    op.drop_column('products', 'use_custom_description')
    op.drop_column('models', 'goods_subtype')
    op.drop_column('models', 'goods_type')
    op.drop_column('models', 'subcategory')
    op.drop_column('models', 'category')
