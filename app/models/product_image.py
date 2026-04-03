from datetime import datetime

from sqlalchemy import String, Integer, Boolean, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, utc_now


class ProductImage(Base):
    __tablename__ = "product_images"
    __table_args__ = (Index("ix_product_images_product_id", "product_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    url: Mapped[str] = mapped_column(String(500))
    filename: Mapped[str] = mapped_column(String(255))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_main: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        default=utc_now
    )

    product: Mapped["Product"] = relationship(back_populates="images")
