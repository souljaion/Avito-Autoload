from datetime import datetime

from sqlalchemy import String, Integer, ForeignKey, Index, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, utc_now


class PhotoPackYandexFolder(Base):
    __tablename__ = "photo_pack_yandex_folders"
    __table_args__ = (Index("ix_photo_pack_yandex_folders_pack_id", "photo_pack_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    photo_pack_id: Mapped[int] = mapped_column(ForeignKey("photo_packs.id", ondelete="CASCADE"))
    public_url: Mapped[str] = mapped_column(String(500))
    public_key: Mapped[str | None] = mapped_column(String(200), default=None)
    folder_name: Mapped[str | None] = mapped_column(String(255), default=None)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    error: Mapped[str | None] = mapped_column(String(500), default=None)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)

    pack: Mapped["PhotoPack"] = relationship(back_populates="yandex_folders")
