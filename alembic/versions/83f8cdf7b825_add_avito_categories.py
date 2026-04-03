"""add_avito_categories

Revision ID: 83f8cdf7b825
Revises: d929ae95352d
Create Date: 2026-03-31 17:13:03.109109

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '83f8cdf7b825'
down_revision: Union[str, None] = 'd929ae95352d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('avito_categories',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('avito_id', sa.Integer(), nullable=True),
        sa.Column('slug', sa.String(length=255), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('parent_id', sa.Integer(), nullable=True),
        sa.Column('show_fields', sa.Boolean(), nullable=False),
        sa.Column('fields_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('synced_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['parent_id'], ['avito_categories.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('avito_categories')
