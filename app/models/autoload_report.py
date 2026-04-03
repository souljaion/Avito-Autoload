from datetime import datetime

from sqlalchemy import String, Integer, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, utc_now


class AutoloadReport(Base):
    __tablename__ = "autoload_reports"
    __table_args__ = (Index("ix_autoload_reports_account_id", "account_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    avito_report_id: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(50), default="pending")
    total_ads: Mapped[int] = mapped_column(Integer, default=0)
    applied_ads: Mapped[int] = mapped_column(Integer, default=0)
    declined_ads: Mapped[int] = mapped_column(Integer, default=0)
    extra: Mapped[dict | None] = mapped_column(JSONB, default=None)

    created_at: Mapped[datetime] = mapped_column(
        default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        default=utc_now,
        onupdate=utc_now,
    )

    account: Mapped["Account"] = relationship(back_populates="autoload_reports")
    items: Mapped[list["AutoloadReportItem"]] = relationship(back_populates="report")
