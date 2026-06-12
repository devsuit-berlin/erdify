"""Framework comparison schema — SQLModel.

The same User/Order schema is expressed in docs/examples/{sqlmodel,sqlalchemy,
pydantic,dataclass} and produces an identical ERD (Pydantic/dataclass require
``--infer-keys``).
"""

from typing import List

from sqlmodel import Field, Relationship, SQLModel


class User(SQLModel, table=True):
    __tablename__: str = "user"

    id: int = Field(primary_key=True)
    name: str
    email: str

    orders: List["Order"] = Relationship(back_populates="user")


class Order(SQLModel, table=True):
    __tablename__: str = "order"

    id: int = Field(primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    total: float

    user: "User" = Relationship(back_populates="orders")
