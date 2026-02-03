"""Data classes for SQLModel to ERD conversion."""

from dataclasses import dataclass, field
from typing import List, Tuple


@dataclass
class FieldInfo:
    """Represents a database field/column."""

    name: str
    type_str: str
    is_primary_key: bool = False
    is_foreign_key: bool = False
    is_nullable: bool = False
    foreign_table: str | None = None
    index: bool = False
    default_value: str | None = None


@dataclass
class EnumInfo:
    """Represents an enum type."""

    name: str
    values: List[str] = field(default_factory=list)


@dataclass
class EntityInfo:
    """Represents a database table/entity."""

    name: str
    table_name: str
    fields: List[FieldInfo] = field(default_factory=list)
    relationships: List[Tuple[str, str, str]] = field(
        default_factory=list
    )  # (target, type, attribute_name)
    is_link_table: bool = False
    base_classes: List[str] = field(default_factory=list)
