import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Integer, String, Boolean, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, utc_now


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    avito_user_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    name: Mapped[str] = mapped_column(String(255))
    client_id: Mapped[str | None] = mapped_column(String(255))
    client_secret: Mapped[str | None] = mapped_column(Text)
    access_token: Mapped[str | None] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None]
    phone: Mapped[str | None] = mapped_column(String(50))
    address: Mapped[str | None] = mapped_column(String(500))
    autoload_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    report_email: Mapped[str | None] = mapped_column(String(255))
    schedule: Mapped[str | None] = mapped_column(String(50))
    avito_sync_minute: Mapped[int | None] = mapped_column(Integer, default=None)
    feed_token: Mapped[str] = mapped_column(
        String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4())
    )
    extra: Mapped[dict | None] = mapped_column(JSONB, default=None)

    created_at: Mapped[datetime] = mapped_column(
        default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        default=utc_now,
        onupdate=utc_now,
    )

    products: Mapped[list["Product"]] = relationship(
        back_populates="account", foreign_keys="[Product.account_id]"
    )
    feed_exports: Mapped[list["FeedExport"]] = relationship(back_populates="account")
    autoload_reports: Mapped[list["AutoloadReport"]] = relationship(
        back_populates="account"
    )
