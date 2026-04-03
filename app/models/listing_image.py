from datetime import datetime

from sqlalchemy import String, Integer, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, utc_now


class ListingImage(Base):
    __tablename__ = "listing_images"
    __table_args__ = (Index("ix_listing_images_listing_id", "listing_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"))
    file_path: Mapped[str] = mapped_column(String(500))
    order: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(
        default=utc_now
    )

    listing: Mapped["Listing"] = relationship(back_populates="images")
