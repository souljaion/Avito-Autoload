"""yandex_disk_integration

Revision ID: 5f2076151cf7
Revises: a1acd81c79d1
Create Date: 2026-04-17 13:30:45.947986

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5f2076151cf7'
down_revision: Union[str, None] = 'a1acd81c79d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # New tables
    op.create_table('product_yandex_folders',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('public_url', sa.String(length=500), nullable=False),
        sa.Column('public_key', sa.String(length=200), nullable=True),
        sa.Column('folder_name', sa.String(length=255), nullable=True),
        sa.Column('last_synced_at', sa.DateTime(), nullable=True),
        sa.Column('error', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_product_yandex_folders_product_id', 'product_yandex_folders', ['product_id'], unique=False)

    op.create_table('product_publish_history',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('published_at', sa.DateTime(), nullable=False),
        sa.Column('removed_at', sa.DateTime(), nullable=True),
        sa.Column('was_uniquified', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_product_publish_history_product_account', 'product_publish_history', ['product_id', 'account_id'], unique=False)

    # New columns on product_images
    op.add_column('product_images', sa.Column('source_type', sa.String(length=20), server_default='local', nullable=False))
    op.add_column('product_images', sa.Column('source_url', sa.String(length=500), nullable=True))
    op.add_column('product_images', sa.Column('yandex_folder_id', sa.Integer(), nullable=True))
    op.add_column('product_images', sa.Column('yandex_file_path', sa.String(length=500), nullable=True))
    op.add_column('product_images', sa.Column('yandex_md5', sa.String(length=32), nullable=True))
    op.add_column('product_images', sa.Column('download_status', sa.String(length=20), server_default='ready', nullable=False))
    op.add_column('product_images', sa.Column('download_error', sa.String(length=500), nullable=True))
    op.add_column('product_images', sa.Column('download_attempts', sa.Integer(), server_default='0', nullable=False))
    op.add_column('product_images', sa.Column('was_uniquified', sa.Boolean(), server_default='false', nullable=False))
    op.create_index(op.f('ix_product_images_yandex_folder_id'), 'product_images', ['yandex_folder_id'], unique=False)
    op.create_foreign_key('fk_product_images_yandex_folder_id', 'product_images', 'product_yandex_folders', ['yandex_folder_id'], ['id'], ondelete='SET NULL')

    # Backfill existing product_images rows
    op.execute("""
        UPDATE product_images SET source_type = CASE
            WHEN url LIKE '/%' THEN 'local'
            WHEN url LIKE 'https://%avito%' OR url LIKE 'http://%avito%' THEN 'avito_cdn'
            ELSE 'local'
        END
        WHERE source_type = 'local'
    """)


def downgrade() -> None:
    # Remove FK and index from product_images
    op.drop_constraint('fk_product_images_yandex_folder_id', 'product_images', type_='foreignkey')
    op.drop_index(op.f('ix_product_images_yandex_folder_id'), table_name='product_images')

    # Remove new columns from product_images
    op.drop_column('product_images', 'was_uniquified')
    op.drop_column('product_images', 'download_attempts')
    op.drop_column('product_images', 'download_error')
    op.drop_column('product_images', 'download_status')
    op.drop_column('product_images', 'yandex_md5')
    op.drop_column('product_images', 'yandex_file_path')
    op.drop_column('product_images', 'yandex_folder_id')
    op.drop_column('product_images', 'source_url')
    op.drop_column('product_images', 'source_type')

    # Drop new tables
    op.drop_index('ix_product_publish_history_product_account', table_name='product_publish_history')
    op.drop_table('product_publish_history')
    op.drop_index('ix_product_yandex_folders_product_id', table_name='product_yandex_folders')
    op.drop_table('product_yandex_folders')
