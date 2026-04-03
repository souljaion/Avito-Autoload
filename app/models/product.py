from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, Text, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, utc_now


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        Index("ix_products_account_id", "account_id"),
        Index("ix_products_status", "status"),
        Index("ix_products_sku", "sku"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    avito_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, index=True, default=None)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    model_id: Mapped[int | None] = mapped_column(ForeignKey("models.id", ondelete="SET NULL"), default=None)
    sku: Mapped[str | None] = mapped_column(String(100))
    brand: Mapped[str | None] = mapped_column(String(255))
    model: Mapped[str | None] = mapped_column(String(255))
    category: Mapped[str | None] = mapped_column(String(255))
    subcategory: Mapped[str | None] = mapped_column(String(255))
    goods_type: Mapped[str | None] = mapped_column(String(255))
    goods_subtype: Mapped[str | None] = mapped_column(String(255))
    size: Mapped[str | None] = mapped_column(String(100))
    color: Mapped[str | None] = mapped_column(String(100))
    material: Mapped[str | None] = mapped_column(String(255))
    condition: Mapped[str | None] = mapped_column(String(100))
    price: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    scheduled_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), default=None
    )
    image_url: Mapped[str | None] = mapped_column(String(500), default=None)
    extra: Mapped[dict | None] = mapped_column(JSONB, default=None)

    created_at: Mapped[datetime] = mapped_column(
        default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        default=utc_now,
        onupdate=utc_now,
    )

    account: Mapped["Account | None"] = relationship(
        back_populates="products", foreign_keys=[account_id]
    )
    model_ref: Mapped["Model | None"] = relationship(back_populates="products")
    images: Mapped[list["ProductImage"]] = relationship(
        back_populates="product", order_by="ProductImage.sort_order"
    )
    listings: Mapped[list["Listing"]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
