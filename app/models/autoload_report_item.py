from datetime import datetime

from sqlalchemy import String, Text, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, utc_now


class AutoloadReportItem(Base):
    __tablename__ = "autoload_report_items"
    __table_args__ = (Index("ix_autoload_report_items_report_id", "report_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(
        ForeignKey("autoload_reports.id", ondelete="CASCADE")
    )
    ad_id: Mapped[str | None] = mapped_column(String(255))
    avito_id: Mapped[str | None] = mapped_column(String(255))
    url: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(50))
    messages: Mapped[dict | None] = mapped_column(JSONB, default=None)
    error_text: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        default=utc_now
    )

    report: Mapped["AutoloadReport"] = relationship(back_populates="items")
