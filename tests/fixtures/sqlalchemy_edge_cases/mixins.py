"""Mixins: columns, foreign keys and relationships declared on plain mixin classes."""

from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class IdMixin:
    id: Mapped[int] = mapped_column(primary_key=True)


class TimestampMixin:
    created: Mapped[str]
    updated: Mapped[str | None]


class OwnedMixin:
    owner_id: Mapped[int] = mapped_column(ForeignKey("owner.id"))

    @declared_attr
    def owner(cls) -> Mapped["Owner"]:
        return relationship("Owner")


class Owner(IdMixin, Base):
    __tablename__ = "owner"

    name: Mapped[str]


class Document(IdMixin, TimestampMixin, OwnedMixin, Base):
    __tablename__ = "document"

    title: Mapped[str]
