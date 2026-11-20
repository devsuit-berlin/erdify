"""A default schema from the declarative base's MetaData(schema=...); a
module-level MetaData for Core tables; Table(..., schema=...)."""

from sqlalchemy import Column, ForeignKey, Integer, MetaData, Table
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    metadata = MetaData(schema="sales")


class Customer(Base):
    __tablename__ = "customer"

    id: Mapped[int] = mapped_column(primary_key=True)


class Order(Base):
    __tablename__ = "order"
    __table_args__ = {"schema": "orders"}

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("sales.customer.id"))


# A Core table on the base's metadata takes its default schema.
customer_tag = Table(
    "customer_tag",
    Base.metadata,
    Column("customer_id", Integer, ForeignKey("sales.customer.id"), primary_key=True),
    Column("tag", Integer, primary_key=True),
)

audit_metadata = MetaData(schema="audit")

audit_log = Table(
    "audit_log",
    audit_metadata,
    Column("id", Integer, primary_key=True),
)

# An explicit schema= wins over the metadata's.
audit_archive = Table(
    "audit_archive",
    audit_metadata,
    Column("id", Integer, primary_key=True),
    schema="archive",
)


class Shipment(Base):
    """A class mapped to a Core table: the table's schema."""

    __table__ = Table(
        "shipment",
        Base.metadata,
        Column("id", Integer, primary_key=True),
        schema="logistics",
    )
