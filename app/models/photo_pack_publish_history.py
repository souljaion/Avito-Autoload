from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, utc_now


class PhotoPackPublishHistory(Base):
    __tablename__ = "photo_pack_publish_history"
    __table_args__ = (
        Index("ix_photo_pack_publish_history_pack_account", "photo_pack_id", "account_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    photo_pack_id: Mapped[int] = mapped_column(ForeignKey("photo_packs.id", ondelete="CASCADE"))
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    published_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    was_uniquified: Mapped[bool] = mapped_column(Boolean, default=False)
