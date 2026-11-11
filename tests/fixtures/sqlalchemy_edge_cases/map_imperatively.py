"""Imperative mapping: a plain class mapped to a Core Table with registry.map_imperatively()."""

from sqlalchemy import Column, ForeignKey, Integer, String, Table
from sqlalchemy.orm import registry, relationship

mapper_registry = registry()

team = Table(
    "team",
    mapper_registry.metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(50), nullable=False),
)

member = Table(
    "member",
    mapper_registry.metadata,
    Column("id", Integer, primary_key=True),
    Column("team_id", ForeignKey("team.id"), nullable=False),
)


class Team:
    pass


class Member:
    pass


mapper_registry.map_imperatively(Team, team)
mapper_registry.map_imperatively(Member, member, properties={"team": relationship(Team)})
