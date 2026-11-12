"""SQLModel Field() settings given in Annotated metadata (SQLModel 0.0.32+, #295)."""

from typing import Annotated

from sqlmodel import Field, SQLModel


class Team(SQLModel, table=True):
    __tablename__ = "team"

    id: Annotated[int | None, Field(primary_key=True)] = None


class Account(SQLModel, table=True):
    __tablename__ = "account"

    id: Annotated[int, Field(primary_key=True)]
    code: Annotated[str, Field(unique=True)]
    # An assigned plain value is the default; the metadata still applies.
    slug: Annotated[str, Field(unique=True)] = "a"
    team_id: Annotated[int | None, Field(foreign_key="team.id")] = None
    # Only the first Field() applies.
    first: Annotated[str, Field(nullable=True), Field(unique=True)]
    # An assigned Field() replaces the one in the metadata.
    replaced: Annotated[str, Field(unique=True)] = Field(index=True)
    plain: str
