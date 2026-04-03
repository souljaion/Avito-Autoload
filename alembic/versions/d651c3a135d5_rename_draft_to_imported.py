"""rename_draft_to_imported

Revision ID: d651c3a135d5
Revises: 8207eb80c7d6
Create Date: 2026-04-02 14:40:19.827031

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd651c3a135d5'
down_revision: Union[str, None] = '8207eb80c7d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE products SET status='imported' "
        "WHERE status='draft' "
        "AND (goods_type IS NULL OR goods_type='') "
        "AND (description IS NULL OR description='')"
    )


def downgrade() -> None:
    op.execute("UPDATE products SET status='draft' WHERE status='imported'")
