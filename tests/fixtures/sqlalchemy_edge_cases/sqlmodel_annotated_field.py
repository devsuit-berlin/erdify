"""SQLModel Field() settings given in Annotated metadata."""

from typing import Annotated

from sqlmodel import Field, SQLModel


class Account(SQLModel, table=True):
    __tablename__ = "account"

    id: Annotated[int, Field(primary_key=True)]
    code: Annotated[str, Field(unique=True)]
    plain: str
