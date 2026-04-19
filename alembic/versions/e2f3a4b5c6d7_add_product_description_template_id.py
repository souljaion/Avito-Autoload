"""add product description_template_id

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-04-19

"""
from alembic import op
import sqlalchemy as sa

revision = "e2f3a4b5c6d7"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column(
            "description_template_id",
            sa.Integer(),
            sa.ForeignKey("description_templates.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_products_description_template_id",
        "products",
        ["description_template_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_products_description_template_id", table_name="products")
    op.drop_column("products", "description_template_id")
