"""Single-table inheritance: subclasses add columns to the parent's table."""

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Vehicle(Base):
    __tablename__ = "vehicle"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str]
    wheels: Mapped[int | None]
    payload: Mapped[int | None]

    __mapper_args__ = {"polymorphic_identity": "vehicle", "polymorphic_on": "kind"}


class Car(Vehicle):
    __mapper_args__ = {"polymorphic_identity": "car"}


class Truck(Vehicle):
    __mapper_args__ = {"polymorphic_identity": "truck"}
