"""Joined-table inheritance: each subclass has its own table keyed by the parent's id."""

from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Employee(Base):
    __tablename__ = "employee"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    type: Mapped[str]

    __mapper_args__ = {"polymorphic_identity": "employee", "polymorphic_on": "type"}


class Engineer(Employee):
    __tablename__ = "engineer"

    id: Mapped[int] = mapped_column(ForeignKey("employee.id"), primary_key=True)
    language: Mapped[str]

    __mapper_args__ = {"polymorphic_identity": "engineer"}


class Manager(Employee):
    __tablename__ = "manager"

    id: Mapped[int] = mapped_column(ForeignKey("employee.id"), primary_key=True)
    budget: Mapped[int | None]

    __mapper_args__ = {"polymorphic_identity": "manager"}
