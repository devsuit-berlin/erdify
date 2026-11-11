"""One-to-one: a unique foreign key, a scalar reverse side and uselist=False."""

from typing import Optional

from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Person(Base):
    __tablename__ = "person"

    id: Mapped[int] = mapped_column(primary_key=True)
    passport: Mapped[Optional["Passport"]] = relationship(back_populates="holder")
    badge: Mapped[Optional["Badge"]] = relationship(uselist=False, back_populates="person")


class Passport(Base):
    __tablename__ = "passport"

    id: Mapped[int] = mapped_column(primary_key=True)
    holder_id: Mapped[int] = mapped_column(ForeignKey("person.id"), unique=True)
    holder: Mapped["Person"] = relationship(back_populates="passport")


class Badge(Base):
    __tablename__ = "badge"

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int | None] = mapped_column(ForeignKey("person.id"), unique=True)
    person: Mapped[Optional["Person"]] = relationship(back_populates="badge")
