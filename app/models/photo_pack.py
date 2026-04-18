from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, utc_now


class PhotoPack(Base):
    __tablename__ = "photo_packs"

    id: Mapped[int] = mapped_column(primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("models.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now,
    )

    model: Mapped["Model"] = relationship(back_populates="photo_packs")
    images: Mapped[list["PhotoPackImage"]] = relationship(
        back_populates="pack", cascade="all, delete-orphan",
        order_by="PhotoPackImage.sort_order",
    )
    yandex_folders: Mapped[list["PhotoPackYandexFolder"]] = relationship(
        back_populates="pack", cascade="all, delete-orphan",
    )
