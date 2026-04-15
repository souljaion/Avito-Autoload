"""add account_description_templates

Revision ID: 5203f001e123
Revises: 789ddf4f6e4b
Create Date: 2026-04-03 13:40:30.261151

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '5203f001e123'
down_revision: Union[str, None] = '789ddf4f6e4b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'account_description_templates',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('account_id', sa.Integer(), sa.ForeignKey('accounts.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('description_template', sa.Text(), nullable=False, server_default=''),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('account_description_templates')
