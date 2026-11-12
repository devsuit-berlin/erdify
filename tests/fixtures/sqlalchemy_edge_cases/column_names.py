"""Explicit column names: mapped_column("name"), name= and key= (#292).

A ForeignKey string resolves through the column key; a value referring to a
module-level mapped_column() is a column.
"""

from sqlalchemy import Column, ForeignKey, String, Table
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class shared:  # noqa: N801 - stands in for a module of shared columns
    owner_fk = mapped_column()


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "account"

    id: Mapped[int] = mapped_column("account_id", primary_key=True)
    email: Mapped[str] = mapped_column("email_address", String(200), unique=True)
    display: Mapped[str | None] = mapped_column(name="display_name")


class Profile(Base):
    __tablename__ = "profile"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[int] = mapped_column("owner_id", ForeignKey("account.account_id"))


class Team(Base):
    __tablename__ = "team"

    id: Mapped[int] = mapped_column("team_no", key="id", primary_key=True)
    code: Mapped[str] = mapped_column(key="ref", unique=True)


class Member(Base):
    __tablename__ = "member"

    id: Mapped[int] = mapped_column(primary_key=True)
    team: Mapped[int] = mapped_column("team_no", ForeignKey("team.id"))
    owner_id: Mapped[int] = shared.owner_fk
    team_code: Mapped[str] = mapped_column(ForeignKey("team.ref"))


member_team = Table(
    "member_team",
    Base.metadata,
    Column("member_id", ForeignKey("member.id"), primary_key=True),
    Column("team_id", ForeignKey("team.id"), primary_key=True),
)
