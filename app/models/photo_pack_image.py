from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, utc_now


class PhotoPackImage(Base):
    __tablename__ = "photo_pack_images"

    id: Mapped[int] = mapped_column(primary_key=True)
    pack_id: Mapped[int] = mapped_column(ForeignKey("photo_packs.id", ondelete="CASCADE"))
    file_path: Mapped[str] = mapped_column(String(500))
    url: Mapped[str] = mapped_column(String(500))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    source_type: Mapped[str] = mapped_column(String(20), default="local", server_default="local")
    source_url: Mapped[str | None] = mapped_column(String(500), default=None)
    yandex_folder_id: Mapped[int | None] = mapped_column(ForeignKey("photo_pack_yandex_folders.id", ondelete="SET NULL"), default=None, index=True)
    yandex_file_path: Mapped[str | None] = mapped_column(String(500), default=None)
    yandex_md5: Mapped[str | None] = mapped_column(String(32), default=None)
    download_status: Mapped[str] = mapped_column(String(20), default="ready", server_default="ready")
    download_error: Mapped[str | None] = mapped_column(String(500), default=None)
    download_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    was_uniquified: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now,
    )

    pack: Mapped["PhotoPack"] = relationship(back_populates="images")
    yandex_folder: Mapped["PhotoPackYandexFolder | None"] = relationship()
