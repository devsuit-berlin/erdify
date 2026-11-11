"""SQLAlchemy / SQLModel reference loader: build a :class:`Schema` from the mapped metadata.

The source is executed as a fresh module. Every declarative base it defines
brings its own registry and ``MetaData``; SQLModel's shared default registry is
swapped for a new one per load, so tables with the same name in different
sources never collide. No database is touched: columns and keys come from
``MetaData.tables``, relationships from ``sqlalchemy.inspect(cls).relationships``
after the mappers are configured.
"""

from __future__ import annotations

import ast
import enum
import sys
import types
from collections.abc import Iterator
from typing import Any
from unittest import mock

import sqlmodel.main
from sqlalchemy import MetaData, Table, UniqueConstraint
from sqlalchemy import exc as sa_exc
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Mapper, RelationshipDirection, RelationshipProperty, registry
from sqlmodel import SQLModel

from erdify.config import FieldInfo, is_structural_link_table

from .schema import Column, Relationship, Schema, Table as SchemaTable

# A top-level name: a relative import in a source fails (it is not
# self-contained) instead of reaching into this package.
MODULE = "erdify_ground_truth_models"


class Unloadable(Exception):
    """The source is not a complete model module on its own.

    Raised only for sources that reference names, modules, classes or tables
    outside themselves (``NameError`` / ``ImportError`` / ``SyntaxError``, a
    relationship to a class the source doesn't define, a foreign key to a
    table it doesn't define), which SQLAlchemy cannot load but erdify handles
    by design. Any other exception propagates and fails the test, so a broken
    harness or an API change can't turn comparisons into silent skips.
    """


class Rejected(Unloadable):
    """SQLAlchemy refuses to create the mapped classes or tables at all.

    ``ArgumentError`` / ``InvalidRequestError`` while a class body is mapped
    (e.g. a mapped class without a primary key, two tables of the same name),
    or ``TypeError`` from class creation (bases with no consistent MRO).
    There is no schema to compare. A source whose classes map but whose mappers
    don't configure (an ambiguous join, a ``back_populates`` naming a missing
    attribute) is not a rejection: the error is reported in
    :attr:`Schema.checks`.
    """


def load(source: str) -> Schema:
    """Execute ``source`` as a models module and normalise its tables and relationships.

    The mappers of the source's registries are configured (what
    ``configure_mappers()`` does on first use of a model), and every foreign key
    is resolved against the source's tables. A configuration error is reported
    by class name in :attr:`Schema.checks`, and the relationships are then left
    out (only the tables are compared).
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise Unloadable(f"SyntaxError: {exc}") from exc
    module = types.ModuleType(MODULE)
    module.__file__ = "<models>"
    # SQLAlchemy resolves string annotations (Mapped["User"]) in the module of
    # the class, looked up in sys.modules.
    sys.modules[MODULE] = module
    sqlmodel_registry = registry()
    swap = mock.patch.multiple(
        SQLModel, _sa_registry=sqlmodel_registry, metadata=sqlmodel_registry.metadata
    )
    registries: set[registry] = {sqlmodel_registry}
    try:
        with swap, mock.patch.object(sqlmodel.main, "default_registry", sqlmodel_registry):
            try:
                exec(compile(tree, "<models>", "exec", dont_inherit=True), module.__dict__)
            except (NameError, ImportError) as exc:
                raise Unloadable(f"{type(exc).__name__}: {exc}") from exc
            except (sa_exc.ArgumentError, sa_exc.InvalidRequestError, TypeError) as exc:
                raise Rejected(f"{type(exc).__name__}: {exc}") from exc
            classes = list(_classes(module))
            # The registries of the mapped classes, and of declarative bases
            # with no mapped class (their metadata may hold Core tables).
            registries |= {sa_inspect(c).registry for c in classes if _is_mapped(c)}
            registries |= {
                c.registry for c in classes if isinstance(vars(c).get("registry"), registry)
            }
            return _schema(module, classes, registries)
    finally:
        for reg in registries:
            reg.dispose()
        del sys.modules[MODULE]


def _schema(module: types.ModuleType, classes: list[type], registries: set[registry]) -> Schema:
    checks: list[str] = []
    for reg in registries:
        try:
            reg.configure()
        except sa_exc.InvalidRequestError as exc:
            if _names_outside_class(exc):
                raise Unloadable(f"{type(exc).__name__}: {exc}") from exc
            checks.append(type(exc).__name__)
        except sa_exc.ArgumentError as exc:
            checks.append(type(exc).__name__)
    mappers = [
        m
        for reg in registries
        for m in reg.mappers
        if m.class_.__module__ == MODULE and _has_own_table(m)
    ]
    metadatas = {reg.metadata for reg in registries} | {
        v for v in vars(module).values() if isinstance(v, MetaData)
    }
    tables = {m.class_.__name__: _table(m.local_table, m if not checks else None) for m in mappers}
    mapped_tables = {m.local_table for m in mappers}
    secondaries = {
        r.secondary
        for m in mappers
        if not checks
        for r in m.relationships
        if r.secondary is not None
    }
    names = {id(v): k for k, v in vars(module).items() if isinstance(v, Table)}
    for metadata in metadatas:
        for table in metadata.tables.values():
            if table in mapped_tables:
                continue
            # erdify draws a Core table that is an association table (#34);
            # one a relationship goes through is part of the schema too.
            if table in secondaries or _is_association(table):
                tables[names.get(id(table), table.name)] = _table(table, None)
    enums = {
        cls.__name__: tuple(cls.__members__)
        for cls in classes
        if issubclass(cls, enum.Enum) and cls is not enum.Enum
    }
    return Schema(tables=tables, enums=enums, checks=tuple(sorted(set(checks))))


def _names_outside_class(exc: Exception) -> bool:
    """A relationship target the source doesn't define.

    SQLAlchemy has no dedicated exception for it; its message says the
    expression "failed to locate a name".
    """
    return "failed to locate a name" in str(exc)


def _is_mapped(cls: type) -> bool:
    try:
        return isinstance(sa_inspect(cls), Mapper)
    except sa_exc.NoInspectionAvailable:
        return False


def _has_own_table(mapper: Mapper[Any]) -> bool:
    """A mapper with a table of its own (not single-table inheritance)."""
    return mapper.inherits is None or mapper.local_table is not mapper.inherits.local_table


def _classes(module: types.ModuleType) -> Iterator[type]:
    """Classes defined in the source, including ones nested in a class body."""
    seen: set[type] = set()
    pending = list(vars(module).values())
    while pending:
        value = pending.pop()
        if isinstance(value, type) and value.__module__ == MODULE and value not in seen:
            seen.add(value)
            yield value
            pending.extend(vars(value).values())


def _is_association(table: Table) -> bool:
    """A composite primary key made up of foreign keys only, as erdify defines it."""
    return is_structural_link_table(
        [
            FieldInfo(c.name, "", is_primary_key=c.primary_key, is_foreign_key=bool(c.foreign_keys))
            for c in table.columns
        ]
    )


def _unique_columns(table: Table) -> set[str]:
    """Columns unique on their own: ``unique=True``, or a single-column unique
    constraint or unique index (``unique=True, index=True`` creates the latter).
    """
    names = {c.name for c in table.columns if c.unique}
    for constraint in table.constraints:
        if isinstance(constraint, UniqueConstraint) and len(constraint.columns) == 1:
            names.update(c.name for c in constraint.columns)
    for index in table.indexes:
        # A partial index (``postgresql_where=`` / ``sqlite_where=``) doesn't
        # make the column unique; neither does an expression index.
        partial = any(
            index.dialect_options[dialect].get("where") is not None
            for dialect in ("postgresql", "sqlite")
        )
        if index.unique and not partial and len(index.expressions) == 1 and len(index.columns) == 1:
            names.update(c.name for c in index.columns)
    return names


def _fk(column: Any) -> str | None:
    if not column.foreign_keys:
        return None
    targets = []
    for fk in column.foreign_keys:
        try:
            target = fk.column
        except sa_exc.NoReferencedTableError as exc:
            raise Unloadable(f"foreign key to a table outside the source: {exc}") from exc
        targets.append(f"{target.table.name}.{target.name}")
    return sorted(targets)[0]


def _table(table: Table, mapper: Mapper[Any] | None) -> SchemaTable:
    unique = _unique_columns(table)
    columns = {
        c.name: Column(
            pk=c.primary_key,
            nullable=bool(c.nullable) and not c.primary_key,
            unique=c.name in unique and not c.primary_key,
            fk=_fk(c),
        )
        for c in table.columns
    }
    relationships = {} if mapper is None else _relationships(mapper)
    return SchemaTable(table=table.name, columns=columns, relationships=relationships)


def _relationships(mapper: Mapper[Any]) -> dict[str, Relationship]:
    """The relationships the class declares, as erdify must draw them.

    Left out: one going through a ``secondary`` table (the association table
    is drawn instead, so erdify adds no direct edge), one created by the other
    side's ``backref=`` (not declared on this class), and one inherited from a
    mapped parent class (it belongs to the parent's entity).
    """
    found: dict[str, Relationship] = {}
    for rel in mapper.relationships:
        if rel.parent is not mapper or rel.secondary is not None or _from_backref(rel):
            continue
        found[rel.key] = Relationship(
            target=rel.mapper.class_.__name__,
            kind="many" if rel.uselist else "one",
            nullable=_nullable(rel),
            # SQLAlchemy sets back_populates on a side declared with backref=
            # too; only a back_populates= the source wrote names the inverse.
            inverse=None if rel.backref else rel.back_populates or None,
        )
    return found


def _from_backref(rel: RelationshipProperty[Any]) -> bool:
    for other in rel._reverse_property:
        backref = other.backref
        name = backref[0] if isinstance(backref, tuple) else backref
        if name == rel.key:
            return True
    return False


def _nullable(rel: RelationshipProperty[Any]) -> bool:
    """Whether a to-one reference may be absent in the database.

    Many-to-one: when one of its foreign-key columns is nullable. A to-one
    reference from the referenced side (a one-to-one's ``uselist=False``
    reverse) can always be absent. A collection is never nullable.
    """
    if rel.uselist:
        return False
    if rel.direction is RelationshipDirection.MANYTOONE:
        return any(c.nullable for c in rel.local_columns)
    return True
