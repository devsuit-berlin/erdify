"""SQLModel: default table names, Optional keys, indexes and uniqueness."""

from typing import Optional

from sqlmodel import Field, SQLModel


class HeroTeam(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    headquarters: str = Field(unique=True)


class SuperHero(SQLModel, table=True):
    __tablename__ = "hero"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    secret_name: str | None = None
    age: Optional[int] = Field(default=None, index=True)
    team_id: Optional[int] = Field(default=None, foreign_key="heroteam.id")
    rival_team_id: int = Field(foreign_key="heroteam.id", nullable=True)
