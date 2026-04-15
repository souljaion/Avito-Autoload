"""add_check_constraint_on_product_status

Revision ID: c8aeb4bc65f9
Revises: 4376a58c7f4a
Create Date: 2026-04-15 10:57:13.680916

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c8aeb4bc65f9'
down_revision: Union[str, None] = '4376a58c7f4a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_products_status",
        "products",
        "status IN ('imported','draft','scheduled','active','published','paused','sold','removed')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_products_status", "products", type_="check")
