"""Data classes for erdify."""

from dataclasses import dataclass, field
from typing import List, Tuple


@dataclass
class FieldInfo:
    """Represents a database field/column.

    Attributes:
        name: Column / attribute name.
        type_str: Type as written in the source (or the mapped Python type for
            Django unless ``django_raw_types``; the lower-cased SQL type for DDL).
        is_primary_key: Part of the primary key.
        is_foreign_key: References another table.
        is_nullable: Column accepts ``NULL``.
        foreign_table: Referenced ``"table.column"`` when ``is_foreign_key``.
        index: Column is indexed.
        default_value: Default value as source text, if any.
        is_unique: Non-primary-key unique constraint (implies a 1:1 relationship
            when the column is also a foreign key).
    """

    name: str
    type_str: str
    is_primary_key: bool = False
    is_foreign_key: bool = False
    is_nullable: bool = False
    foreign_table: str | None = None
    index: bool = False
    default_value: str | None = None
    is_unique: bool = False


@dataclass
class EnumInfo:
    """Represents an enum type.

    Attributes:
        name: Enum class (or SQL type) name.
        values: Enum members, in declaration order.
    """

    name: str
    values: List[str] = field(default_factory=list)


@dataclass
class EntityInfo:
    """Represents a database table/entity.

    Attributes:
        name: Class name (or table name for SQL DDL); the key in the entities dict.
        table_name: Database table name.
        fields: Columns, in declaration order.
        relationships: ``(target, type, attribute)`` tuples, where ``target`` is
            the related entity name and ``type`` is one of ``"one"``, ``"many"``,
            ``"one_to_one"``, ``"many_to_many"``.
        is_link_table: A detected many-to-many join table (see
            :func:`is_structural_link_table`).
        base_classes: Names of the class's direct base classes.
        source: The model kind that produced the entity: one of ``MODEL_SOURCES``
            (``sqlmodel``, ``sqlalchemy``, ``django``, ``dataclass``,
            ``pydantic``) or ``sql`` for SQL DDL.
    """

    name: str
    table_name: str
    fields: List[FieldInfo] = field(default_factory=list)
    relationships: List[Tuple[str, str, str]] = field(
        default_factory=list
    )  # (target, type, attribute_name)
    is_link_table: bool = False
    base_classes: List[str] = field(default_factory=list)
    source: str = "sqlmodel"


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
