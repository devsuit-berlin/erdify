"""Data classes for erdify."""

from dataclasses import dataclass, field
from typing import Dict, List, Tuple


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
        is_unique: Unique on its own (implies a 1:1 relationship when the
            column is also a foreign key). Never set on a table's *sole*
            primary-key column, which the key already makes unique; a member
            of a composite primary key keeps its own uniqueness (#331), see
            :func:`normalize_key_uniqueness`.
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
        nullable_relationships: Attribute names of ``"one"`` relationships whose
            reference is optional (e.g. ``user: User | None``); drawn as
            zero-or-one on the target side. Foreign-key columns carry their own
            ``FieldInfo.is_nullable`` instead.
        inverse_relationships: Relationship attribute -> the attribute of the
            other side's relationship it pairs with, when the source names it
            (SQLAlchemy / SQLModel ``back_populates=``). Both sides are then
            drawn as one edge.
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
    nullable_relationships: List[str] = field(default_factory=list)
    inverse_relationships: Dict[str, str] = field(default_factory=dict)


def normalize_key_uniqueness(fields: List[FieldInfo]) -> None:
    """Clear ``is_unique`` on a sole primary-key column, where it is redundant.

    A member of a composite primary key is not unique by the key, so its own
    ``unique`` / single-column unique constraint stays (#331). Shared by every
    parser backend, which keep ``is_unique`` as declared until this runs.
    """
    pks = [f for f in fields if f.is_primary_key]
    if len(pks) == 1:
        pks[0].is_unique = False


def is_sole_primary_key(field: FieldInfo, fields: List[FieldInfo]) -> bool:
    """Whether ``field`` is the only primary-key column among ``fields``."""
    return field.is_primary_key and sum(f.is_primary_key for f in fields) == 1


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
