from datetime import datetime

from sqlalchemy import String, Integer, Boolean, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, utc_now


class ProductImage(Base):
    __tablename__ = "product_images"
    __table_args__ = (Index("ix_product_images_product_id", "product_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    url: Mapped[str] = mapped_column(String(500))
    filename: Mapped[str] = mapped_column(String(255))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_main: Mapped[bool] = mapped_column(Boolean, default=False)
    source_type: Mapped[str] = mapped_column(String(20), default="local", server_default="local")
    source_url: Mapped[str | None] = mapped_column(String(500), default=None)
    yandex_folder_id: Mapped[int | None] = mapped_column(ForeignKey("product_yandex_folders.id", ondelete="SET NULL"), default=None, index=True)
    yandex_file_path: Mapped[str | None] = mapped_column(String(500), default=None)
    yandex_md5: Mapped[str | None] = mapped_column(String(32), default=None)
    download_status: Mapped[str] = mapped_column(String(20), default="ready", server_default="ready")
    download_error: Mapped[str | None] = mapped_column(String(500), default=None)
    download_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    was_uniquified: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    created_at: Mapped[datetime] = mapped_column(
        default=utc_now
    )

    product: Mapped["Product"] = relationship(back_populates="images")
    yandex_folder: Mapped["ProductYandexFolder | None"] = relationship()
