"""Nullability: Optional annotations, explicit nullable=, primary keys and defaults."""

from typing import Optional, Union

from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Team(Base):
    __tablename__ = "team"

    id: Mapped[int] = mapped_column(primary_key=True)


class Member(Base):
    __tablename__ = "member"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    nickname: Mapped[Optional[str]]
    motto: Mapped[Union[str, None]]
    bio: Mapped[str | None]
    forced_null: Mapped[str] = mapped_column(nullable=True)
    forced_not_null: Mapped[str | None] = mapped_column(nullable=False)
    unspecified: Mapped[str | None] = mapped_column(nullable=None)
    with_default: Mapped[str] = mapped_column(default="x")
    team_id: Mapped[int | None] = mapped_column(ForeignKey("team.id"))
    mentor_id: Mapped[int] = mapped_column(ForeignKey("team.id"))
