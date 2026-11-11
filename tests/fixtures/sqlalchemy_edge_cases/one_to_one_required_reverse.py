"""One-to-one whose referenced side declares the reference as required."""

from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Device(Base):
    __tablename__ = "device"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Not enforceable: a device row can exist without a license row.
    license: Mapped["License"] = relationship(back_populates="device")


class License(Base):
    __tablename__ = "license"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("device.id"), unique=True)
    device: Mapped["Device"] = relationship(back_populates="license")
