"""A ClassVar member of a SQLModel table model is no column."""

from typing import ClassVar

from sqlmodel import Field, SQLModel


class Hero(SQLModel, table=True):
    counter: ClassVar[int] = 0
    id: int | None = Field(default=None, primary_key=True)
    name: str
