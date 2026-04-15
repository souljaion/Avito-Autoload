"""add report item unique constraint

Revision ID: f6a7b8c9d1e2
Revises: e5f6a7b8c9d1
Create Date: 2026-04-14 19:10:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'f6a7b8c9d1e2'
down_revision: Union[str, None] = 'e5f6a7b8c9d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Remove any existing duplicates before adding constraint
    op.execute("""
        DELETE FROM autoload_report_items a
        USING autoload_report_items b
        WHERE a.id > b.id
          AND a.report_id = b.report_id
          AND a.ad_id = b.ad_id
    """)
    op.create_unique_constraint(
        'uq_report_items_report_ad',
        'autoload_report_items',
        ['report_id', 'ad_id'],
    )


def downgrade() -> None:
    op.drop_constraint('uq_report_items_report_ad', 'autoload_report_items', type_='unique')
