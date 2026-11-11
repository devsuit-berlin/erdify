"""Foreign key spellings: positional, keyword, module-qualified, with options."""

import sqlalchemy as sa
from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Region(Base):
    __tablename__ = "region"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(unique=True)


class Store(Base):
    __tablename__ = "store"

    id: Mapped[int] = mapped_column(primary_key=True)
    region_id: Mapped[int] = mapped_column(ForeignKey("region.id", ondelete="CASCADE"))
    backup_region_id: Mapped[int | None] = mapped_column(sa.ForeignKey("region.id"))
    region_code: Mapped[str] = mapped_column(sa.String(5), ForeignKey("region.code"))
    typed_id: Mapped[int] = mapped_column(sa.Integer, sa.ForeignKey("region.id"), index=True)
