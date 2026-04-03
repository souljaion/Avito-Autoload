from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, utc_now


class PhotoPackImage(Base):
    __tablename__ = "photo_pack_images"

    id: Mapped[int] = mapped_column(primary_key=True)
    pack_id: Mapped[int] = mapped_column(ForeignKey("photo_packs.id", ondelete="CASCADE"))
    file_path: Mapped[str] = mapped_column(String(500))
    url: Mapped[str] = mapped_column(String(500))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now,
    )

    pack: Mapped["PhotoPack"] = relationship(back_populates="images")
