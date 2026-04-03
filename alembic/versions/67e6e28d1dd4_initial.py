"""initial

Revision ID: 67e6e28d1dd4
Revises:
Create Date: 2026-03-31 05:41:40.796398

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '67e6e28d1dd4'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("client_id", sa.String(255), nullable=True),
        sa.Column("client_secret", sa.Text(), nullable=True),
        sa.Column("access_token", sa.Text(), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("address", sa.String(500), nullable=True),
        sa.Column("autoload_enabled", sa.Boolean(), server_default="false"),
        sa.Column("report_email", sa.String(255), nullable=True),
        sa.Column("schedule", sa.String(50), nullable=True),
        sa.Column("extra", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=True),
        sa.Column("sku", sa.String(100), nullable=True),
        sa.Column("brand", sa.String(255), nullable=True),
        sa.Column("model", sa.String(255), nullable=True),
        sa.Column("category", sa.String(255), nullable=True),
        sa.Column("subcategory", sa.String(255), nullable=True),
        sa.Column("size", sa.String(100), nullable=True),
        sa.Column("color", sa.String(100), nullable=True),
        sa.Column("condition", sa.String(100), nullable=True),
        sa.Column("price", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), server_default="draft"),
        sa.Column("extra", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_products_account_id", "products", ["account_id"])
    op.create_index("ix_products_status", "products", ["status"])
    op.create_index("ix_products_sku", "products", ["sku"])

    op.create_table(
        "product_images",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0"),
        sa.Column("is_main", sa.Boolean(), server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_product_images_product_id", "product_images", ["product_id"])

    op.create_table(
        "feed_exports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("file_path", sa.String(500), nullable=False),
        sa.Column("products_count", sa.Integer(), server_default="0"),
        sa.Column("status", sa.String(20), server_default="generated"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_feed_exports_account_id", "feed_exports", ["account_id"])

    op.create_table(
        "autoload_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("avito_report_id", sa.String(255), nullable=True),
        sa.Column("status", sa.String(50), server_default="pending"),
        sa.Column("total_ads", sa.Integer(), server_default="0"),
        sa.Column("applied_ads", sa.Integer(), server_default="0"),
        sa.Column("declined_ads", sa.Integer(), server_default="0"),
        sa.Column("extra", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_autoload_reports_account_id", "autoload_reports", ["account_id"])

    op.create_table(
        "autoload_report_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("autoload_reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ad_id", sa.String(255), nullable=True),
        sa.Column("avito_id", sa.String(255), nullable=True),
        sa.Column("url", sa.String(500), nullable=True),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("messages", postgresql.JSONB(), nullable=True),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_autoload_report_items_report_id", "autoload_report_items", ["report_id"])


def downgrade() -> None:
    op.drop_table("autoload_report_items")
    op.drop_table("autoload_reports")
    op.drop_table("feed_exports")
    op.drop_table("product_images")
    op.drop_table("products")
    op.drop_table("accounts")
