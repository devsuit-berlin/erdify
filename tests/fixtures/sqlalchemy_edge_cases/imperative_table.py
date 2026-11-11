"""A class mapped to an explicit __table__ (declarative with an imperative table)."""

from sqlalchemy import Column, ForeignKey, Integer, String, Table
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Warehouse(Base):
    __tablename__ = "warehouse"

    id: Mapped[int] = mapped_column(primary_key=True)


class Bin(Base):
    __table__ = Table(
        "bin",
        Base.metadata,
        Column("id", Integer, primary_key=True),
        Column("label", String(20), nullable=False),
        Column("warehouse_id", ForeignKey("warehouse.id")),
    )

    id: Mapped[int]
    label: Mapped[str]
    warehouse_id: Mapped[int | None]
