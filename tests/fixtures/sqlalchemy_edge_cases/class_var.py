"""A ClassVar member of a SQLAlchemy model or mixin is no column."""

from typing import ClassVar

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class CountedMixin:
    counter: ClassVar[int]


class Account(CountedMixin, Base):
    __tablename__ = "account"

    label: ClassVar[set[str]] = set()
    id: Mapped[int] = mapped_column(primary_key=True)
