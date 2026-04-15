"""add brand to models

Revision ID: 789ddf4f6e4b
Revises: c4d5e6f7a8b9
Create Date: 2026-04-03 13:37:04.655900

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '789ddf4f6e4b'
down_revision: Union[str, None] = 'c4d5e6f7a8b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('models', sa.Column('brand', sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column('models', 'brand')
