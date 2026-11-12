"""SQLModel: a column key set through sa_column_kwargs, referenced from a Core table (#292)."""

from typing import Optional

from sqlalchemy import Column, ForeignKey, Table
from sqlmodel import Field, SQLModel


class Owner(SQLModel, table=True):
    __tablename__ = "owner"

    id: Optional[int] = Field(
        default=None, primary_key=True, sa_column_kwargs={"name": "owner_pk", "key": "id"}
    )


class Tag(SQLModel, table=True):
    __tablename__ = "tag"

    id: Optional[int] = Field(default=None, primary_key=True)


owner_tag = Table(
    "owner_tag",
    SQLModel.metadata,
    Column("owner_id", ForeignKey("owner.id"), primary_key=True),
    Column("tag_id", ForeignKey("tag.id"), primary_key=True),
)
