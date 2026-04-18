from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, utc_now


class ProductPublishHistory(Base):
    __tablename__ = "product_publish_history"
    __table_args__ = (
        Index("ix_product_publish_history_product_account", "product_id", "account_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    published_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    was_uniquified: Mapped[bool] = mapped_column(Boolean, default=False)
