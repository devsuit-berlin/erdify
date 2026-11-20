"""SQLModel tables in a database schema: __table_args__ = {"schema": ...}."""

from sqlmodel import Field, SQLModel


class Team(SQLModel, table=True):
    __table_args__ = {"schema": "league"}

    id: int | None = Field(default=None, primary_key=True)


class Hero(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    team_id: int | None = Field(default=None, foreign_key="league.team.id")
