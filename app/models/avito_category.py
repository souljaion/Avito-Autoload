from datetime import datetime

from sqlalchemy import String, Integer, ForeignKey, Boolean
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, utc_now


class AvitoCategory(Base):
    __tablename__ = "avito_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    avito_id: Mapped[int | None] = mapped_column(Integer)
    slug: Mapped[str | None] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("avito_categories.id", ondelete="CASCADE")
    )
    show_fields: Mapped[bool] = mapped_column(Boolean, default=False)
    fields_data: Mapped[dict | None] = mapped_column(JSONB)
    synced_at: Mapped[datetime] = mapped_column(
        default=utc_now
    )

    parent: Mapped["AvitoCategory | None"] = relationship(
        remote_side="AvitoCategory.id", backref="children"
    )
