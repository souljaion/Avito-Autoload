"""add_models_table

Revision ID: 8207eb80c7d6
Revises: a1b2c3d4e5f6
Create Date: 2026-04-02 14:17:13.450415

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '8207eb80c7d6'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('models',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.add_column('products', sa.Column('model_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_products_model_id', 'products', 'models', ['model_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    op.drop_constraint('fk_products_model_id', 'products', type_='foreignkey')
    op.drop_column('products', 'model_id')
    op.drop_table('models')
