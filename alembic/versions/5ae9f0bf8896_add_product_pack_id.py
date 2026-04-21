"""add_product_pack_id

Revision ID: 5ae9f0bf8896
Revises: a45fb6f4ac7f
Create Date: 2026-04-21 16:36:55.043722

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '5ae9f0bf8896'
down_revision: Union[str, None] = 'a45fb6f4ac7f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('products', sa.Column('pack_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_products_pack_id'), 'products', ['pack_id'], unique=False)
    op.create_foreign_key('fk_products_pack_id', 'products', 'photo_packs', ['pack_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    op.drop_constraint('fk_products_pack_id', 'products', type_='foreignkey')
    op.drop_index(op.f('ix_products_pack_id'), table_name='products')
    op.drop_column('products', 'pack_id')
