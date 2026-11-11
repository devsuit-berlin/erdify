"""Two foreign keys to one table, disambiguated with foreign_keys=."""

from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Address(Base):
    __tablename__ = "address"

    id: Mapped[int] = mapped_column(primary_key=True)


class Shipment(Base):
    __tablename__ = "shipment"

    id: Mapped[int] = mapped_column(primary_key=True)
    origin_id: Mapped[int] = mapped_column(ForeignKey("address.id"))
    destination_id: Mapped[int | None] = mapped_column(ForeignKey("address.id"))
    origin: Mapped["Address"] = relationship(foreign_keys=[origin_id])
    destination: Mapped["Address | None"] = relationship(foreign_keys="Shipment.destination_id")
