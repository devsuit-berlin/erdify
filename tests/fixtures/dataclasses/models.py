"""Sample dataclass models for testing - inventory schema."""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Warehouse:
    """Warehouse dataclass."""

    id: int
    name: str
    location: Optional[str] = None

    items: List["Item"] = field(default_factory=list)


@dataclass
class Item:
    """Item dataclass with a nested warehouse reference."""

    id: int
    warehouse_id: int
    label: str
    note: str | None = None

    warehouse: Optional["Warehouse"] = None
