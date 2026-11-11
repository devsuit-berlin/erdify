"""A ternary association table: a composite primary key of three foreign keys."""

from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Doctor(Base):
    __tablename__ = "doctor"

    id: Mapped[int] = mapped_column(primary_key=True)


class Patient(Base):
    __tablename__ = "patient"

    id: Mapped[int] = mapped_column(primary_key=True)


class Room(Base):
    __tablename__ = "room"

    id: Mapped[int] = mapped_column(primary_key=True)


class Appointment(Base):
    __tablename__ = "appointment"

    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctor.id"), primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patient.id"), primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("room.id"), primary_key=True)
