"""SQLModel relationships: back_populates, Optional sides and sa_relationship_kwargs."""

from typing import List, Optional

from sqlmodel import Field, Relationship, SQLModel


class Team(SQLModel, table=True):
    __tablename__ = "team"

    id: Optional[int] = Field(default=None, primary_key=True)
    heroes: List["Hero"] = Relationship(
        back_populates="team", sa_relationship_kwargs={"foreign_keys": "[Hero.team_id]"}
    )
    captains: list["Hero"] = Relationship(
        sa_relationship_kwargs={
            "back_populates": "captain_of",
            "foreign_keys": "[Hero.captain_of_id]",
        }
    )


class Hero(SQLModel, table=True):
    __tablename__ = "hero"

    id: Optional[int] = Field(default=None, primary_key=True)
    team_id: Optional[int] = Field(default=None, foreign_key="team.id")
    team: Optional[Team] = Relationship(
        back_populates="heroes", sa_relationship_kwargs={"foreign_keys": "[Hero.team_id]"}
    )
    captain_of_id: Optional[int] = Field(default=None, foreign_key="team.id")
    captain_of: Optional["Team"] = Relationship(
        sa_relationship_kwargs={
            "back_populates": "captains",
            "foreign_keys": "[Hero.captain_of_id]",
        }
    )
