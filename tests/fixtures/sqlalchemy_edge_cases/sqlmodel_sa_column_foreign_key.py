"""SQLModel foreign key declared inside sa_column=Column(...)."""

from typing import Optional

from sqlalchemy import Column, ForeignKey, Integer
from sqlmodel import Field, SQLModel


class Owner(SQLModel, table=True):
    __tablename__ = "owner"

    id: Optional[int] = Field(default=None, primary_key=True)


class Pet(SQLModel, table=True):
    __tablename__ = "pet"

    id: Optional[int] = Field(default=None, primary_key=True)
    owner_id: Optional[int] = Field(default=None, sa_column=Column(Integer, ForeignKey("owner.id")))
