"""A relationship() assigned without an annotation (legacy declarative style)."""

from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Coach(Base):
    __tablename__ = "coach"

    id: Mapped[int] = mapped_column(primary_key=True)


class Squad(Base):
    __tablename__ = "squad"
    __allow_unmapped__ = True

    id: Mapped[int] = mapped_column(primary_key=True)
    coach_id: Mapped[int] = mapped_column(ForeignKey("coach.id"))
    coach = relationship("Coach")
