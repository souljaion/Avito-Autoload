from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, utc_now


class Model(Base):
    __tablename__ = "models"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    brand: Mapped[str | None] = mapped_column(String(100), default=None)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(100), default=None)
    subcategory: Mapped[str | None] = mapped_column(String(100), default=None)
    goods_type: Mapped[str | None] = mapped_column(String(100), default=None)
    goods_subtype: Mapped[str | None] = mapped_column(String(100), default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now,
    )

    products: Mapped[list["Product"]] = relationship(back_populates="model_ref")
    photo_packs: Mapped[list["PhotoPack"]] = relationship(
        back_populates="model", cascade="all, delete-orphan",
        order_by="PhotoPack.id.desc()",
    )
    variants: Mapped[list["ModelVariant"]] = relationship(
        back_populates="model", cascade="all, delete-orphan",
        order_by="ModelVariant.id",
    )
