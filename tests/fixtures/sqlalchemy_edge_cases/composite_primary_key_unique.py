"""A member of a composite primary key that is unique on its own (#331)."""

from sqlalchemy import Column, ForeignKey, Integer, Table, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Person(Base):
    __tablename__ = "person"

    id: Mapped[int] = mapped_column(primary_key=True, unique=True)  # sole key: no UK


class Tenant(Base):
    __tablename__ = "tenant"

    id: Mapped[int] = mapped_column(primary_key=True)


class Seat(Base):
    """A link table whose person side is unique: 1:N, not M:N."""

    __tablename__ = "seat"

    person_id: Mapped[int] = mapped_column(ForeignKey("person.id"), primary_key=True, unique=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), primary_key=True)


class Desk(Base):
    __tablename__ = "desk"
    __table_args__ = (UniqueConstraint("desk_no"),)

    room: Mapped[int] = mapped_column(primary_key=True)
    desk_no: Mapped[int] = mapped_column(primary_key=True)


seat_core = Table(
    "seat_core",
    Base.metadata,
    Column("person_id", ForeignKey("person.id"), primary_key=True, unique=True),
    Column("tenant_id", ForeignKey("tenant.id"), primary_key=True),
)

desk_core = Table(
    "desk_core",
    Base.metadata,
    Column("room", Integer, primary_key=True),
    Column("desk_no", Integer, primary_key=True),
    UniqueConstraint("desk_no"),
)
