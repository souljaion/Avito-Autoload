from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, utc_now


class Model(Base):
    __tablename__ = "models"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now,
    )

    products: Mapped[list["Product"]] = relationship(back_populates="model_ref")
    photo_packs: Mapped[list["PhotoPack"]] = relationship(
        back_populates="model", cascade="all, delete-orphan",
        order_by="PhotoPack.id.desc()",
    )
