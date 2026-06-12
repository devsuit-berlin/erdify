"""Framework comparison schema — dataclass.

Same schema as docs/examples/sqlmodel. Render with ``--infer-keys`` to derive
the primary/foreign keys from the field names and get an identical ERD.
"""

from dataclasses import dataclass, field
from typing import List


@dataclass
class User:
    id: int
    name: str
    email: str

    orders: List["Order"] = field(default_factory=list)


@dataclass
class Order:
    id: int
    user_id: int
    total: float

    user: "User" = None
