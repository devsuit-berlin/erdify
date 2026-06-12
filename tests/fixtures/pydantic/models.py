"""Sample Pydantic models for testing - billing schema."""

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel


class Priority(Enum):
    """Invoice priority enumeration."""

    LOW = "low"
    HIGH = "high"


class Identifiable(BaseModel):
    """Base model with an id - itself a (direct) BaseModel subclass."""

    id: int


class Customer(Identifiable):
    """Customer model - inherits BaseModel indirectly via Identifiable."""

    name: str
    email: Optional[str] = None

    invoices: List["Invoice"] = []


class Invoice(BaseModel):
    """Invoice model with a nested customer reference."""

    id: int
    customer_id: int
    priority: Priority = Priority.LOW
    amount: float
    note: str | None = None

    customer: "Customer"
