"""The schema of __table_args__ as SQLAlchemy takes it: from a mixin or an
abstract base, never from a mapped parent; a tuple ending in a dict."""

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class InReporting:
    __table_args__ = {"schema": "reporting"}


class Report(InReporting, Base):
    __tablename__ = "report"

    id: Mapped[int] = mapped_column(primary_key=True)


class Archived(Base):
    __abstract__ = True
    __table_args__ = {"schema": "archive"}


class OldReport(Archived):
    __tablename__ = "old_report"

    id: Mapped[int] = mapped_column(primary_key=True)


class Party(Base):
    __tablename__ = "party"
    __table_args__ = (UniqueConstraint("code"), {"schema": "crm"})

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str]


class Person(Party):
    """A joined-table subclass: not in its parent's schema."""

    __tablename__ = "person"

    id: Mapped[int] = mapped_column(ForeignKey("crm.party.id"), primary_key=True)


class Draft(InReporting, Base):
    """Its own __table_args__ (no schema) wins over the mixin's."""

    __tablename__ = "draft"
    __table_args__ = ({"comment": "unpublished"},)

    id: Mapped[int] = mapped_column(primary_key=True)
