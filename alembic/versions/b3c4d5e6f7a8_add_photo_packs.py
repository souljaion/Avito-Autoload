"""add_photo_packs

Revision ID: b3c4d5e6f7a8
Revises: 8207eb80c7d6
Create Date: 2026-04-02 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, None] = 'd651c3a135d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'photo_packs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('model_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['model_id'], ['models.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_photo_packs_model_id', 'photo_packs', ['model_id'])

    op.create_table(
        'photo_pack_images',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('pack_id', sa.Integer(), nullable=False),
        sa.Column('file_path', sa.String(length=500), nullable=False),
        sa.Column('url', sa.String(length=500), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['pack_id'], ['photo_packs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_photo_pack_images_pack_id', 'photo_pack_images', ['pack_id'])


def downgrade() -> None:
    op.drop_index('ix_photo_pack_images_pack_id', table_name='photo_pack_images')
    op.drop_table('photo_pack_images')
    op.drop_index('ix_photo_packs_model_id', table_name='photo_packs')
    op.drop_table('photo_packs')
