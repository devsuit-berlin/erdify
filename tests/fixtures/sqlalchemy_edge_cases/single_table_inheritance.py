"""Single-table inheritance: subclasses add columns to the parent's table.

Also through a mixin, a nested subclass, ``__tablename__ = None`` and a column
two subclasses share with ``use_existing_column=True``.
"""

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Vehicle(Base):
    __tablename__ = "vehicle"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str]

    __mapper_args__ = {"polymorphic_identity": "vehicle", "polymorphic_on": "kind"}


class Towing:
    hitch: Mapped[str | None]


class Car(Vehicle):
    wheels: Mapped[int | None]
    seats: Mapped[int | None] = mapped_column(use_existing_column=True)

    __mapper_args__ = {"polymorphic_identity": "car"}


class Truck(Towing, Vehicle):
    __tablename__ = None

    payload: Mapped[int | None]
    seats: Mapped[int] = mapped_column(use_existing_column=True)

    __mapper_args__ = {"polymorphic_identity": "truck"}


class Tractor(Truck):
    horsepower: Mapped[int | None]

    __mapper_args__ = {"polymorphic_identity": "tractor"}
