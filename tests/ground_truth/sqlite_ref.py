"""SQL DDL reference loader: build a :class:`Schema` from what SQLite creates.

The DDL is executed in a fresh in-memory SQLite database (stdlib ``sqlite3``,
no new dependency) and the schema is read back from SQLite's catalog:

- ``PRAGMA table_xinfo``: columns (generated columns included), ``notnull``
  and ``pk``.
- ``PRAGMA foreign_key_list``: each foreign key column and the table / column
  it references. A bare ``REFERENCES t`` references ``t``'s primary key, and
  names are resolved the way SQLite resolves them (case-insensitively).
- ``PRAGMA index_list`` / ``index_info``: a column is unique when a
  single-column unique index covers it, whether a ``UNIQUE`` constraint
  created it or a ``CREATE UNIQUE INDEX``. Partial and expression indexes don't
  make a column unique.

One normalisation: a primary-key column is not nullable. SQLite lets a
non-``INTEGER`` (or composite) primary key of a rowid table hold ``NULL``, a
legacy quirk its documentation calls a bug; erdify follows the SQL standard
there (docs/frameworks/sql.md).

The DDL runs statement by statement, as written. For a source in another
dialect (PostgreSQL ``DEFAULT NOW()``), a statement SQLite rejects is
transpiled to SQLite by sqlglot and run again; only those statements depend
on sqlglot, whose SQLite output is not reliable enough to run everything
through it (it adds ``NULLS LAST`` to index columns, for one). SQLite has no
enum types, so a ``CREATE TYPE`` is dropped and enums are not compared.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict

from .schema import Column, Schema, Table


class Unloadable(Exception):
    """SQLite cannot run the source as written.

    Raised for DDL that SQLite doesn't support (``ALTER TABLE ... ADD
    CONSTRAINT``, another dialect's syntax that isn't transpiled), for sources
    that are not DDL at all, for sources sqlglot can't transpile, and for a
    bare ``REFERENCES t`` to a table the source doesn't define (no key to
    resolve it to). There is no schema to compare.
    """


def load(sql: str, *, dialect: str | None = None) -> Schema:
    """Execute ``sql`` in a fresh in-memory SQLite database and normalise its tables.

    ``dialect`` names the sqlglot dialect the source is written in (``None``:
    run as written). :attr:`Schema.checks` lists what SQLite's own foreign-key
    validation reports for the source (a parent table that doesn't exist, a
    parent key that isn't a primary key or unique: ``foreign key mismatch``).

    Raises:
        Unloadable: SQLite rejects a statement (also once transpiled).
    """
    connection = sqlite3.connect(":memory:")
    try:
        for statement in _statements(sql):
            _execute(connection, statement, dialect)
        return _read(connection)
    finally:
        connection.close()


def _statements(sql: str) -> list[str]:
    """Split ``sql`` into complete statements the way SQLite's shell does."""
    statements: list[str] = []
    pending = ""
    for part in sql.split(";"):
        pending += part + ";"
        if sqlite3.complete_statement(pending):
            statements.append(pending)
            pending = ""
    if pending.rstrip(";").strip():
        statements.append(pending)  # an unterminated last statement
    return statements


def _execute(connection: sqlite3.Connection, statement: str, dialect: str | None) -> None:
    try:
        connection.executescript(statement)
        return
    except sqlite3.Error as exc:
        if dialect is None:
            raise Unloadable(f"{type(exc).__name__}: {exc}") from exc
        error = exc
    transpiled = _transpile(statement, dialect)
    if transpiled is None:
        return  # CREATE TYPE: SQLite has no types
    try:
        connection.executescript(transpiled)
    except sqlite3.Error as exc:
        raise Unloadable(
            f"{type(error).__name__}: {error}; transpiled from {dialect}: {exc}"
        ) from exc


def _transpile(statement: str, dialect: str) -> str | None:
    """``statement`` in SQLite's dialect, or ``None`` for a ``CREATE TYPE``."""
    import sqlglot
    from sqlglot import exp

    try:
        parsed = sqlglot.parse_one(statement, read=dialect)
    except sqlglot.errors.ParseError as exc:
        raise Unloadable(f"sqlglot can't parse the {dialect} statement: {exc}") from exc
    if isinstance(parsed, exp.Create) and (parsed.args.get("kind") or "").upper() == "TYPE":
        return None
    return parsed.sql(dialect="sqlite") + ";"


def _read(connection: sqlite3.Connection) -> Schema:
    names = [
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite\\_%' ESCAPE '\\' ORDER BY name"
        )
    ]
    by_lower = {name.lower(): name for name in names}
    columns = {name: _columns(connection, name) for name in names}

    tables: dict[str, Table] = {}
    for name in names:
        info = columns[name]
        pk = {c for c, (_, is_pk) in info.items() if is_pk}
        unique = _unique_columns(connection, name) - pk
        fks = _foreign_keys(connection, name, by_lower, columns)
        tables[name] = Table(
            table=name,
            columns={
                col: Column(
                    pk=is_pk,
                    nullable=not notnull and not is_pk,
                    unique=col in unique,
                    fk=fks.get(col),
                )
                for col, (notnull, is_pk) in info.items()
            },
        )
    return Schema(tables=tables, checks=_checks(connection, names, by_lower))


def _columns(connection: sqlite3.Connection, table: str) -> dict[str, tuple[bool, bool]]:
    """Column name -> (NOT NULL, part of the primary key), in declaration order.

    ``table_xinfo`` also lists generated columns (``hidden`` 2 / 3); ``hidden``
    1 is a virtual table's hidden column, not part of the table's schema.
    """
    rows = connection.execute(f"PRAGMA table_xinfo({_quote(table)})").fetchall()
    return {
        name: (bool(notnull), pk > 0)
        for _cid, name, _type, notnull, _default, pk, hidden in rows
        if hidden != 1
    }


def _primary_key(connection: sqlite3.Connection, table: str) -> list[str]:
    rows = connection.execute(f"PRAGMA table_info({_quote(table)})").fetchall()
    return [row[1] for row in sorted((r for r in rows if r[5] > 0), key=lambda r: r[5])]


def _unique_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    """Columns that a single-column, non-partial unique index covers on its own."""
    unique: set[str] = set()
    for _seq, index, is_unique, _origin, partial in connection.execute(
        f"PRAGMA index_list({_quote(table)})"
    ).fetchall():
        if not is_unique or partial:
            continue
        cols = connection.execute(f"PRAGMA index_info({_quote(index)})").fetchall()
        # An expression index has a NULL column name.
        if len(cols) == 1 and cols[0][2] is not None:
            unique.add(cols[0][2])
    return unique


def _foreign_keys(
    connection: sqlite3.Connection,
    table: str,
    by_lower: dict[str, str],
    columns: dict[str, dict[str, tuple[bool, bool]]],
) -> dict[str, str]:
    """Local column -> ``"table.column"`` it references, resolved like SQLite does.

    The parent table and column are matched case-insensitively against the
    declared names; a bare ``REFERENCES t`` pairs the local columns with
    ``t``'s primary key in order. A parent that doesn't exist keeps the name as
    written (SQLite's validation reports it in :attr:`Schema.checks`).
    """
    keys: dict[int, list[tuple[int, str, str, str | None]]] = defaultdict(list)
    for fk_id, seq, parent, local, remote, *_ in connection.execute(
        f"PRAGMA foreign_key_list({_quote(table)})"
    ).fetchall():
        keys[fk_id].append((seq, parent, local, remote))

    found: dict[str, str] = {}
    # The lowest id is the constraint declared last; take the first declared.
    for fk_id in sorted(keys, reverse=True):
        parts = sorted(keys[fk_id])
        parent = by_lower.get(parts[0][1].lower(), parts[0][1])
        parent_pk = _primary_key(connection, parent) if parent in columns else []
        parent_cols = {c.lower(): c for c in columns.get(parent, {})}
        for seq, _parent, local, remote in parts:
            if remote is None:
                if parent not in columns:
                    raise Unloadable(
                        f"{table} references {parent}, which the source doesn't define, "
                        "without naming the column: there is no key to compare"
                    )
                remote = parent_pk[seq] if seq < len(parent_pk) else "?"
            local = _declared(local, columns[table])
            found.setdefault(local, f"{parent}.{parent_cols.get(remote.lower(), remote)}")
    return found


def _declared(name: str, columns: dict[str, tuple[bool, bool]]) -> str:
    return next((c for c in columns if c.lower() == name.lower()), name)


def _checks(
    connection: sqlite3.Connection, names: list[str], by_lower: dict[str, str]
) -> tuple[str, ...]:
    """What SQLite reports once foreign keys are enforced: one entry per table."""
    connection.execute("PRAGMA foreign_keys = ON")
    found: list[str] = []
    for name in names:
        parents = {row[2] for row in connection.execute(f"PRAGMA foreign_key_list({_quote(name)})")}
        if any(parent.lower() not in by_lower for parent in parents):
            found.append(f"{name}: no such table")
            continue
        try:
            connection.execute(f"PRAGMA foreign_key_check({_quote(name)})").fetchall()
        except sqlite3.DatabaseError as exc:
            if "foreign key mismatch" not in str(exc):
                raise
            found.append(f"{name}: foreign key mismatch")
    return tuple(found)


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'
