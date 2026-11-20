"""Tables of the same name in two database schemas, one referencing the other (#353)."""

from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class CoreCustomer(Base):
    __tablename__ = "customer"
    __table_args__ = {"schema": "core"}

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str]


class MartCustomer(Base):
    __tablename__ = "customer"
    __table_args__ = {"schema": "mart"}

    id: Mapped[int] = mapped_column(primary_key=True)
    core_id: Mapped[int | None] = mapped_column(ForeignKey("core.customer.id"))
