"""SQLModel many-to-many with link_model=, and a link model with a payload column."""

from typing import Optional

from sqlmodel import Field, Relationship, SQLModel


class HeroPowerLink(SQLModel, table=True):
    __tablename__ = "hero_power_link"

    hero_id: Optional[int] = Field(default=None, foreign_key="hero.id", primary_key=True)
    power_id: Optional[int] = Field(default=None, foreign_key="power.id", primary_key=True)


class Hero(SQLModel, table=True):
    __tablename__ = "hero"

    id: Optional[int] = Field(default=None, primary_key=True)
    powers: list["Power"] = Relationship(back_populates="heroes", link_model=HeroPowerLink)


class Power(SQLModel, table=True):
    __tablename__ = "power"

    id: Optional[int] = Field(default=None, primary_key=True)
    heroes: list[Hero] = Relationship(back_populates="powers", link_model=HeroPowerLink)


class Training(SQLModel, table=True):
    __tablename__ = "training"

    hero_id: int = Field(foreign_key="hero.id", primary_key=True)
    power_id: int = Field(foreign_key="power.id", primary_key=True)
    hours: int = 0
