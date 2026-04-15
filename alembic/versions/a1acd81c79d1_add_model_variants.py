"""add_model_variants

Revision ID: a1acd81c79d1
Revises: c8aeb4bc65f9
Create Date: 2026-04-15 13:13:36.042343

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1acd81c79d1'
down_revision: Union[str, None] = 'c8aeb4bc65f9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "model_variants",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("model_id", sa.Integer, sa.ForeignKey("models.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("size", sa.String(20), nullable=True),
        sa.Column("price", sa.Integer, nullable=True),
        sa.Column("pack_id", sa.Integer, sa.ForeignKey("photo_packs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("ix_model_variants_model_id", "model_variants", ["model_id"])

    op.add_column("products", sa.Column("variant_id", sa.Integer, sa.ForeignKey("model_variants.id", ondelete="SET NULL"), nullable=True))
    op.create_index("ix_products_variant_id", "products", ["variant_id"])

    # --- Data migration: create default variants from existing products ---
    conn = op.get_bind()

    # Find models that have products with size or price
    models_with_products = conn.execute(sa.text("""
        SELECT DISTINCT m.id AS model_id, p.size, p.price
        FROM models m
        JOIN products p ON p.model_id = m.id
        WHERE p.status NOT IN ('removed', 'sold')
        ORDER BY m.id
    """)).fetchall()

    # Group by model_id, take first product's size+price as the default variant
    seen_models = set()
    for row in models_with_products:
        mid = row[0]
        if mid in seen_models:
            continue
        seen_models.add(mid)
        size = row[1]
        price = row[2]

        # Find pack_id used for this model (first pack if any)
        pack_row = conn.execute(sa.text(
            "SELECT id FROM photo_packs WHERE model_id = :mid ORDER BY id LIMIT 1"
        ), {"mid": mid}).fetchone()
        pack_id = pack_row[0] if pack_row else None

        result = conn.execute(sa.text(
            "INSERT INTO model_variants (model_id, name, size, price, pack_id) "
            "VALUES (:mid, :name, :size, :price, :pack_id) RETURNING id"
        ), {"mid": mid, "name": "Основной", "size": size, "price": price, "pack_id": pack_id})
        variant_id = result.fetchone()[0]

        conn.execute(sa.text(
            "UPDATE products SET variant_id = :vid WHERE model_id = :mid AND status NOT IN ('removed', 'sold')"
        ), {"vid": variant_id, "mid": mid})


def downgrade() -> None:
    op.drop_index("ix_products_variant_id", table_name="products")
    op.drop_column("products", "variant_id")
    op.drop_index("ix_model_variants_model_id", table_name="model_variants")
    op.drop_table("model_variants")
