"""MappedAsDataclass: plain defaults and init=False keys.

`x: Mapped[T] = <plain value>` maps no column (#294); `= None` does.
"""

from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column, relationship


class Base(MappedAsDataclass, DeclarativeBase):
    pass


class Shelf(Base):
    __tablename__ = "shelf"

    id: Mapped[int] = mapped_column(primary_key=True, init=False)
    note: Mapped[str | None] = None
    label: Mapped[str] = "unnamed"
    slots: Mapped[int] = 0


class Jar(Base):
    __tablename__ = "jar"

    id: Mapped[int] = mapped_column(primary_key=True, init=False)
    shelf_id: Mapped[int | None] = mapped_column(ForeignKey("shelf.id"), default=None)
    shelf: Mapped["Shelf | None"] = relationship(default=None)
