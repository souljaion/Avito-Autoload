from datetime import datetime

from sqlalchemy import ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, utc_now


class PackUsageHistory(Base):
    __tablename__ = "pack_usage_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    pack_id: Mapped[int] = mapped_column(ForeignKey("photo_packs.id", ondelete="CASCADE"))
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    uniquified: Mapped[bool] = mapped_column(Boolean, default=False)
    used_at: Mapped[datetime] = mapped_column(default=utc_now)

    pack: Mapped["PhotoPack"] = relationship()
    account: Mapped["Account"] = relationship()
