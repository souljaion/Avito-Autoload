"""add_model_price

Revision ID: a45fb6f4ac7f
Revises: e2f3a4b5c6d7
Create Date: 2026-04-21 10:49:58.301842

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a45fb6f4ac7f'
down_revision: Union[str, None] = 'e2f3a4b5c6d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('models', sa.Column('price', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('models', 'price')
