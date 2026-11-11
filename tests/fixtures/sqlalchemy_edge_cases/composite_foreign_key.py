"""A composite foreign key, which SQLAlchemy can only declare in __table_args__."""

from sqlalchemy import ForeignKeyConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Season(Base):
    __tablename__ = "season"

    year: Mapped[int] = mapped_column(primary_key=True)
    league: Mapped[str] = mapped_column(primary_key=True)


class Match(Base):
    __tablename__ = "match"
    __table_args__ = (
        ForeignKeyConstraint(["season_year", "season_league"], ["season.year", "season.league"]),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    season_year: Mapped[int]
    season_league: Mapped[str]
