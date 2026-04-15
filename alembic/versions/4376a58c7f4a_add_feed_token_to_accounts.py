"""add_feed_token_to_accounts

Revision ID: 4376a58c7f4a
Revises: 941696e9f7b7
Create Date: 2026-04-15 10:02:07.059586

"""
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4376a58c7f4a'
down_revision: Union[str, None] = '941696e9f7b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add nullable column first
    op.add_column("accounts", sa.Column("feed_token", sa.String(36), nullable=True))

    # 2. Populate existing rows with uuid4 values
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id FROM accounts")).fetchall()
    for row in rows:
        token = str(uuid.uuid4())
        conn.execute(
            sa.text("UPDATE accounts SET feed_token = :token WHERE id = :id"),
            {"token": token, "id": row[0]},
        )

    # 3. Add NOT NULL and UNIQUE constraints
    op.alter_column("accounts", "feed_token", nullable=False)
    op.create_unique_constraint("uq_accounts_feed_token", "accounts", ["feed_token"])


def downgrade() -> None:
    op.drop_constraint("uq_accounts_feed_token", "accounts", type_="unique")
    op.drop_column("accounts", "feed_token")
