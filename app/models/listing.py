from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, utc_now


class Listing(Base):
    __tablename__ = "listings"
    __table_args__ = (
        Index("ix_listings_product_id", "product_id"),
        Index("ix_listings_account_id", "account_id"),
        Index("ix_listings_status", "status"),
        Index("ix_listings_scheduled", "scheduled_at", postgresql_where="status = 'scheduled'"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(20), default="draft")
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    avito_id: Mapped[int | None] = mapped_column(BigInteger, default=None)

    created_at: Mapped[datetime] = mapped_column(
        default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        default=utc_now,
        onupdate=utc_now,
    )

    product: Mapped["Product"] = relationship(back_populates="listings")
    account: Mapped["Account"] = relationship()
    images: Mapped[list["ListingImage"]] = relationship(
        back_populates="listing", order_by="ListingImage.order",
        cascade="all, delete-orphan",
    )
