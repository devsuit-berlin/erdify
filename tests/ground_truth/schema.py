"""Normalised schema shape shared by erdify and every reference loader."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from erdify.config import EntityInfo
from erdify.parser import parse_models_directory


@dataclass(frozen=True)
class Column:
    """One database column, reduced to what an ERD must get right.

    ``unique`` excludes primary-key columns (a primary key is unique by
    definition, and erdify only marks ``UK`` on the others). ``fk`` is the
    referenced ``"table.column"``.
    """

    pk: bool = False
    nullable: bool = False
    unique: bool = False
    fk: str | None = None


@dataclass(frozen=True)
class Table:
    """One entity: its table name, columns and many-to-many edges.

    ``m2m`` holds ``(attribute, target entity)`` pairs for many-to-many
    relationships drawn as a direct edge (no join-table entity).
    """

    table: str
    columns: dict[str, Column]
    m2m: frozenset[tuple[str, str]] = frozenset()


@dataclass
class Schema:
    """Entities keyed by class name, plus enums keyed by name (member names)."""

    tables: dict[str, Table] = field(default_factory=dict)
    enums: dict[str, tuple[str, ...]] = field(default_factory=dict)


def from_erdify(path: Path, source: str) -> Schema:
    """Parse ``path`` with erdify and normalise the entities of ``source``."""
    entities, enums = parse_models_directory(path)
    return Schema(
        tables={
            name: _table(entity) for name, entity in entities.items() if entity.source == source
        },
        enums={name: tuple(enum.values) for name, enum in enums.items()},
    )


def _table(entity: EntityInfo) -> Table:
    columns = {
        f.name: Column(
            pk=f.is_primary_key,
            nullable=f.is_nullable,
            unique=f.is_unique and not f.is_primary_key,
            fk=f.foreign_table if f.is_foreign_key else None,
        )
        for f in entity.fields
    }
    m2m = frozenset(
        (attr, target) for target, kind, attr in entity.relationships if kind == "many_to_many"
    )
    return Table(table=entity.table_name, columns=columns, m2m=m2m)
