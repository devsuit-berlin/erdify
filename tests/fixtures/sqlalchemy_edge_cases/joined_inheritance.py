"""Joined-table inheritance: each subclass has its own table keyed by the parent's id.

The parent's columns (and its mixins') stay in the parent's table; a mixin only
the subclass inherits is copied into the subclass's table, except for an
attribute the mapped parent already declares.
"""

from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Stamped:
    created: Mapped[str | None]


class Audited:
    note: Mapped[str | None]
    type: Mapped[str | None]  # the parent's column wins


class Employee(Stamped, Base):
    __tablename__ = "employee"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    type: Mapped[str]

    __mapper_args__ = {"polymorphic_identity": "employee", "polymorphic_on": "type"}


class Engineer(Audited, Employee):
    __tablename__ = "engineer"

    id: Mapped[int] = mapped_column(ForeignKey("employee.id"), primary_key=True)
    language: Mapped[str]

    __mapper_args__ = {"polymorphic_identity": "engineer"}


class Manager(Employee):
    __tablename__ = "manager"

    id: Mapped[int] = mapped_column(ForeignKey("employee.id"), primary_key=True)
    budget: Mapped[int | None]

    __mapper_args__ = {"polymorphic_identity": "manager"}
