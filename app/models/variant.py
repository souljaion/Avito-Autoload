from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, utc_now


class ModelVariant(Base):
    __tablename__ = "model_variants"

    id: Mapped[int] = mapped_column(primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("models.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(50))
    size: Mapped[str | None] = mapped_column(String(20), default=None)
    price: Mapped[int | None] = mapped_column(Integer, default=None)
    pack_id: Mapped[int | None] = mapped_column(ForeignKey("photo_packs.id", ondelete="SET NULL"), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    model: Mapped["Model"] = relationship(back_populates="variants")
    pack: Mapped["PhotoPack | None"] = relationship()
    products: Mapped[list["Product"]] = relationship(back_populates="variant")
