"""Uniqueness: unique=, unique indexes, UniqueConstraint and Index in __table_args__."""

from sqlalchemy import Index, String, UniqueConstraint, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Product(Base):
    __tablename__ = "product"
    __table_args__ = (
        UniqueConstraint("sku"),
        UniqueConstraint("vendor", "vendor_ref"),
        Index("ix_product_slug", "slug", unique=True),
        Index("ix_product_ean", "ean", unique=True, sqlite_where=None),
        Index("ix_product_code", "code", unique=True, postgresql_where="code IS NOT NULL"),
        Index("ix_product_name", "name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    serial: Mapped[str] = mapped_column(unique=True)
    barcode: Mapped[str] = mapped_column(unique=True, index=True)
    sku: Mapped[str]
    vendor: Mapped[str]
    vendor_ref: Mapped[str]
    slug: Mapped[str]
    ean: Mapped[str]
    code: Mapped[str | None]
    unique_false: Mapped[str] = mapped_column(unique=False)


class Voucher(Base):
    """An expression index is not uniqueness of the column ("skip" may repeat)."""

    __tablename__ = "voucher"
    __table_args__ = (Index("ix_voucher_code", func.nullif(text("code"), "skip"), unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str]
