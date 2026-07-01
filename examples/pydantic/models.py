"""Framework comparison schema — Pydantic.

Same schema as docs/examples/sqlmodel. Render with ``--infer-keys`` to derive
the primary/foreign keys from the field names and get an identical ERD.
"""

from typing import List

from pydantic import BaseModel


class User(BaseModel):
    id: int
    name: str
    email: str

    orders: List["Order"] = []


class Order(BaseModel):
    id: int
    user_id: int
    total: float

    user: "User"
