from datetime import datetime

from sqlalchemy import String, Integer, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, utc_now


class FeedExport(Base):
    __tablename__ = "feed_exports"
    __table_args__ = (Index("ix_feed_exports_account_id", "account_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    file_path: Mapped[str] = mapped_column(String(500))
    products_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(50), default="generated")
    uploaded_at: Mapped[datetime | None] = mapped_column(default=None)
    upload_response: Mapped[dict | None] = mapped_column(JSONB, default=None)

    created_at: Mapped[datetime] = mapped_column(
        default=utc_now
    )

    account: Mapped["Account"] = relationship(back_populates="feed_exports")
