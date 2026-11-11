"""SQLModel columns configured through sa_column, sa_type and sa_column_kwargs."""

from typing import Optional

from sqlalchemy import Column, String
from sqlmodel import Field, SQLModel


class Pet(SQLModel, table=True):
    __tablename__ = "pet"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(sa_type=String(30))
    nickname: str = Field(sa_column_kwargs={"name": "pet_nickname"})
    tag: str = Field(sa_column=Column("tag_code", String(8), unique=True, nullable=False))
