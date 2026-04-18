"""yandex_disk_phase2_photo_packs

Revision ID: 311820dce3e8
Revises: 5f2076151cf7
Create Date: 2026-04-17 14:50:02.035520

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '311820dce3e8'
down_revision: Union[str, None] = '5f2076151cf7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── New table: photo_pack_yandex_folders ──
    op.create_table('photo_pack_yandex_folders',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('photo_pack_id', sa.Integer(), nullable=False),
        sa.Column('public_url', sa.String(length=500), nullable=False),
        sa.Column('public_key', sa.String(length=200), nullable=True),
        sa.Column('folder_name', sa.String(length=255), nullable=True),
        sa.Column('last_synced_at', sa.DateTime(), nullable=True),
        sa.Column('error', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['photo_pack_id'], ['photo_packs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_photo_pack_yandex_folders_pack_id', 'photo_pack_yandex_folders', ['photo_pack_id'], unique=False)

    # ── New table: photo_pack_publish_history ──
    op.create_table('photo_pack_publish_history',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('photo_pack_id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('published_at', sa.DateTime(), nullable=False),
        sa.Column('removed_at', sa.DateTime(), nullable=True),
        sa.Column('was_uniquified', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['photo_pack_id'], ['photo_packs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_photo_pack_publish_history_pack_account', 'photo_pack_publish_history', ['photo_pack_id', 'account_id'], unique=False)

    # ── Extend photo_pack_images with 9 new columns ──
    op.add_column('photo_pack_images', sa.Column('source_type', sa.String(length=20), server_default='local', nullable=False))
    op.add_column('photo_pack_images', sa.Column('source_url', sa.String(length=500), nullable=True))
    op.add_column('photo_pack_images', sa.Column('yandex_folder_id', sa.Integer(), nullable=True))
    op.add_column('photo_pack_images', sa.Column('yandex_file_path', sa.String(length=500), nullable=True))
    op.add_column('photo_pack_images', sa.Column('yandex_md5', sa.String(length=32), nullable=True))
    op.add_column('photo_pack_images', sa.Column('download_status', sa.String(length=20), server_default='ready', nullable=False))
    op.add_column('photo_pack_images', sa.Column('download_error', sa.String(length=500), nullable=True))
    op.add_column('photo_pack_images', sa.Column('download_attempts', sa.Integer(), server_default='0', nullable=False))
    op.add_column('photo_pack_images', sa.Column('was_uniquified', sa.Boolean(), server_default='false', nullable=False))
    op.create_index(op.f('ix_photo_pack_images_yandex_folder_id'), 'photo_pack_images', ['yandex_folder_id'], unique=False)
    op.create_foreign_key('fk_photo_pack_images_yandex_folder_id', 'photo_pack_images', 'photo_pack_yandex_folders', ['yandex_folder_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    # ── Remove FK and index from photo_pack_images ──
    op.drop_constraint('fk_photo_pack_images_yandex_folder_id', 'photo_pack_images', type_='foreignkey')
    op.drop_index(op.f('ix_photo_pack_images_yandex_folder_id'), table_name='photo_pack_images')

    # ── Remove 9 new columns from photo_pack_images ──
    op.drop_column('photo_pack_images', 'was_uniquified')
    op.drop_column('photo_pack_images', 'download_attempts')
    op.drop_column('photo_pack_images', 'download_error')
    op.drop_column('photo_pack_images', 'download_status')
    op.drop_column('photo_pack_images', 'yandex_md5')
    op.drop_column('photo_pack_images', 'yandex_file_path')
    op.drop_column('photo_pack_images', 'yandex_folder_id')
    op.drop_column('photo_pack_images', 'source_url')
    op.drop_column('photo_pack_images', 'source_type')

    # ── Drop new tables ──
    op.drop_index('ix_photo_pack_publish_history_pack_account', table_name='photo_pack_publish_history')
    op.drop_table('photo_pack_publish_history')
    op.drop_index('ix_photo_pack_yandex_folders_pack_id', table_name='photo_pack_yandex_folders')
    op.drop_table('photo_pack_yandex_folders')
