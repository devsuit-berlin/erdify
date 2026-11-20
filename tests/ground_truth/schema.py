"""Normalised schema shape shared by erdify and every reference loader."""

from __future__ import annotations

from collections.abc import Iterable
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
class Relationship:
    """A declared ORM relationship (``relationship()`` / ``Relationship()``).

    ``kind`` is ``"one"`` (a to-one reference) or ``"many"`` (a collection).
    ``nullable`` says whether a to-one reference may be absent; ``inverse`` is
    the other side's attribute when the source names it (``back_populates=``).
    """

    target: str
    kind: str
    nullable: bool = False
    inverse: str | None = None


@dataclass(frozen=True)
class Table:
    """One entity: its table name, columns, many-to-many edges and relationships.

    ``m2m`` holds ``(attribute, target entity)`` pairs for many-to-many
    relationships drawn as a direct edge (no join-table entity).
    ``relationships`` maps attribute names to declared ORM relationships; only
    reference loaders that compare them (SQLAlchemy / SQLModel) fill it.
    ``schema`` is the database schema (SQLAlchemy ``Table.schema``) and
    ``app`` the Django app label (``_meta.app_label``); only the loaders whose
    library has them fill them.
    """

    table: str
    columns: dict[str, Column]
    m2m: frozenset[tuple[str, str]] = frozenset()
    relationships: dict[str, Relationship] = field(default_factory=dict)
    schema: str | None = None
    app: str | None = None


@dataclass
class Schema:
    """Entities keyed by class name (``module.Class`` for a name several share,
    #367), plus enums keyed by name (member names).

    ``checks`` holds the ids of the errors the framework's own validation
    reports for the source (Django's system checks), empty for erdify. It is
    not part of the schema comparison.
    """

    tables: dict[str, Table] = field(default_factory=dict)
    enums: dict[str, tuple[str, ...]] = field(default_factory=dict)
    checks: tuple[str, ...] = ()


def from_erdify(
    path: Path,
    source: str | Iterable[str],
    *,
    relationships: bool = False,
    sql_dialect: str | None = None,
    schema: bool = False,
    app: bool = False,
    include: list[str] | None = None,
) -> Schema:
    """Parse ``path`` with erdify and normalise the entities of ``source``.

    ``source`` is one of erdify's model sources (``"sql"`` for DDL) or several
    of them; ``relationships`` also normalises the declared relationships,
    ``schema`` the database schema and ``app`` the Django app label.
    ``path`` may be a single file (a ``.sql`` file is parsed with
    ``sql_dialect``); ``include`` selects the files of a directory (default
    ``models.py``), e.g. ``["**/*.py"]`` for a source of several modules.
    """
    sources = {source} if isinstance(source, str) else set(source)
    entities, enums = parse_models_directory(
        path, sql_dialect=sql_dialect, include_patterns=include
    )
    return Schema(
        tables={
            name: _table(entity, relationships, schema=schema, app=app)
            for name, entity in entities.items()
            if entity.source in sources
        },
        enums={name: tuple(enum.values) for name, enum in enums.items()},
    )


def _table(
    entity: EntityInfo, relationships: bool = False, *, schema: bool = False, app: bool = False
) -> Table:
    columns = {
        f.name: Column(
            pk=f.is_primary_key,
            nullable=f.is_nullable,
            unique=f.is_unique,  # never set on a sole primary key (#331)
            fk=f.foreign_table if f.is_foreign_key else None,
        )
        for f in entity.fields
    }
    m2m = frozenset(
        (attr, target) for target, kind, attr in entity.relationships if kind == "many_to_many"
    )
    rels = (
        {
            attr: Relationship(
                target=target,
                kind=kind,
                nullable=attr in entity.nullable_relationships,
                inverse=entity.inverse_relationships.get(attr),
            )
            for target, kind, attr in entity.relationships
        }
        if relationships
        else {}
    )
    return Table(
        table=entity.table_name,
        columns=columns,
        m2m=m2m,
        relationships=rels,
        schema=entity.schema if schema else None,
        app=entity.app if app else None,
    )
