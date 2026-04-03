from datetime import datetime

from sqlalchemy import BigInteger, Integer, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, utc_now


class ItemStats(Base):
    __tablename__ = "item_stats"
    __table_args__ = (
        Index("ix_item_stats_product_id", "product_id"),
        Index("ix_item_stats_captured", "captured_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    listing_id: Mapped[int | None] = mapped_column(ForeignKey("listings.id", ondelete="SET NULL"), default=None)
    avito_id: Mapped[int | None] = mapped_column(BigInteger)
    views: Mapped[int] = mapped_column(Integer, default=0)
    contacts: Mapped[int] = mapped_column(Integer, default=0)
    favorites: Mapped[int] = mapped_column(Integer, default=0)
    price: Mapped[int | None] = mapped_column(Integer)
    captured_at: Mapped[datetime] = mapped_column(
        default=utc_now
    )
