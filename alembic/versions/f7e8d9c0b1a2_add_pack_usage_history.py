"""add pack_usage_history

Revision ID: f7e8d9c0b1a2
Revises: 5203f001e123
Create Date: 2026-04-03 19:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f7e8d9c0b1a2'
down_revision: Union[str, None] = '5203f001e123'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'pack_usage_history',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('pack_id', sa.Integer(), sa.ForeignKey('photo_packs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('account_id', sa.Integer(), sa.ForeignKey('accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('uniquified', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('used_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('pack_usage_history')
