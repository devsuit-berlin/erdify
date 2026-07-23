"""Data classes for erdify."""

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
    source: str = "sqlmodel"  # one of: sqlmodel, sqlalchemy, pydantic, dataclass


def is_structural_link_table(fields: List[FieldInfo]) -> bool:
    """Return True if fields describe a join table: a composite primary key
    made up entirely of foreign keys, with no payload columns.

    This covers binary association tables (two FKs) as well as ternary and
    higher-order ones (three or more FKs), regardless of the class or table
    name (#35, #118). A single-column PK/FK is an extension table, not a join
    table, so at least two columns are required.

    Shared by every parser backend so the definition cannot drift between them.
    """
    if len(fields) < 2:
        return False
    return all(f.is_foreign_key and f.is_primary_key for f in fields)
