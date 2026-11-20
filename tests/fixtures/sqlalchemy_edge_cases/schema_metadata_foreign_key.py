"""An unqualified ForeignKey under MetaData(schema=...) targets that schema (#370)."""

from sqlalchemy import Column, ForeignKey, Integer, MetaData, Table
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    metadata = MetaData(schema="sales")


class Customer(Base):
    __tablename__ = "customer"

    id: Mapped[int] = mapped_column(primary_key=True)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customer.id"))


# A Core table on the same metadata: its foreign key resolves the same way.
order_note = Table(
    "order_note",
    Base.metadata,
    Column("id", Integer, primary_key=True),
    Column("order_id", ForeignKey("orders.id")),
)
