"""SQL DDL frontend for erdify (optional, requires the `sql` extra: sqlglot)."""

import logging
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

from .config import (
    EntityInfo,
    EnumInfo,
    FieldInfo,
    is_structural_link_table,
    normalize_key_uniqueness,
)
from .parser import ModelParseError
from .parser.discovery import DEFAULT_EXCLUDE_DIRS, _match_include


def discover_sql_files(
    base: Path,
    include_patterns: list[str],
    exclude_paths: list[str],
    use_default_excludes: bool,
) -> list[Path]:
    """Find .sql files under `base` matching `include_patterns`.

    Mirrors the Python scan: prunes DEFAULT_EXCLUDE_DIRS during the walk and
    skips files matching `exclude_paths` (path relative to base, or any segment).
    """
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(base):
        if use_default_excludes:
            dirnames[:] = [d for d in dirnames if d not in DEFAULT_EXCLUDE_DIRS]
        dpath = Path(dirpath)
        for filename in filenames:
            if not filename.endswith(".sql"):
                continue
            candidate = dpath / filename
            try:
                rel = candidate.relative_to(base).as_posix()
            except ValueError:
                rel = candidate.as_posix()
            if not _match_include(rel, filename, include_patterns):
                continue
            segments = rel.split("/")[:-1]
            if use_default_excludes and any(s in DEFAULT_EXCLUDE_DIRS for s in segments):
                continue
            if any(
                fnmatchcase(rel, p) or any(fnmatchcase(s, p) for s in segments)
                for p in exclude_paths
            ):
                continue
            found.append(candidate)
    return sorted(found)


def _lookup(key: str, keys: dict[str, str]) -> str | None:
    """The declared name ``key`` names: an exact key, else the one case-insensitive match."""
    if key in keys:
        return keys[key]
    matches = [name for k, name in keys.items() if k.lower() == key.lower()]
    return matches[0] if len(matches) == 1 else None


def _split_statements(tokens: list[Any], semicolon: Any) -> list[list[Any]]:
    """Group tokens into statements at each semicolon (empty statements dropped)."""
    statements: list[list[Any]] = [[]]
    for token in tokens:
        if token.token_type == semicolon:
            statements.append([])
        else:
            statements[-1].append(token)
    return [s for s in statements if s]


#: Words that may stand between CREATE and TABLE in a plain table definition.
_TABLE_PREFIXES = {"TEMP", "TEMPORARY", "UNLOGGED", "GLOBAL", "LOCAL"}


def _index(names: list[str], name: str) -> int:
    return names.index(name) if name in names else len(names)


def _matching_paren(names: list[str]) -> int | None:
    """Index of the parenthesis closing the first one opened, if any."""
    depth = 0
    for i, name in enumerate(names):
        if name == "L_PAREN":
            depth += 1
        elif name == "R_PAREN":
            depth -= 1
            if depth == 0:
                return i
    return None


@contextmanager
def _held_warnings(logger: logging.Logger) -> Iterator[list[logging.LogRecord]]:
    """Hold back what ``logger`` logs; the caller may replay the records."""
    held: list[logging.LogRecord] = []

    def hold(record: logging.LogRecord) -> bool:
        held.append(record)
        return False

    logger.addFilter(hold)
    try:
        yield held
    finally:
        logger.removeFilter(hold)


class SqlDependencyError(RuntimeError):
    """Raised when SQL parsing is requested without the optional sqlglot dep."""


class SqlSchemaParser:
    """Parse SQL DDL files into erdify's IR using sqlglot (lazy-imported).

    Public API: the constructor and :meth:`parse`. Every other attribute and
    method is internal and may change in any release.

    Args:
        files: The ``.sql`` files to parse, in order. Use
            :func:`erdify.parse_models_directory` to discover them from a directory.
        dialect: sqlglot dialect name (e.g. ``"postgres"``). ``None`` uses
            sqlglot's dialect-agnostic mode.
        exclude_patterns: Case-sensitive globs; a table is dropped if one
            matches its name.
        strict: Raise :class:`~erdify.ModelParseError` if any file fails to
            parse, instead of reporting it on stderr and skipping it.
    """

    def __init__(
        self,
        files: list[Path],
        *,
        dialect: str | None = None,
        exclude_patterns: list[str] | None = None,
        strict: bool = False,
    ):
        self.files = files
        self.strict = strict
        #: (file, message) for every file that failed to parse in the last run.
        self._parse_errors: list[tuple[Path, str]] = []
        self.dialect = dialect
        self.exclude_patterns = exclude_patterns or []
        self._entities: dict[str, EntityInfo] = {}
        self._enums: dict[str, EnumInfo] = {}
        #: Table name -> its primary-key columns, in key order.
        self._primary_keys: dict[str, list[str]] = {}
        #: Name keys (identifiers as the dialect folds them) -> declared names,
        #: for tables and, per table, for columns.
        self._table_keys: dict[str, str] = {}
        self._column_keys: dict[str, dict[str, str]] = {}
        #: Enum type name keys -> declared names.
        self._enum_keys: dict[str, str] = {}
        #: Columns of a user-defined type: (field, schema prefix, type name key),
        #: matched to the enums in _finalize().
        self._typed_fields: list[tuple[FieldInfo, str, str]] = []
        self._dialect: Any = None

    def parse(self) -> tuple[dict[str, EntityInfo], dict[str, EnumInfo]]:
        """Parse ``CREATE TABLE``, ``CREATE TYPE ... AS ENUM``, ``CREATE INDEX``
        and ``ALTER TABLE ... FOREIGN KEY`` statements from all files.

        Each statement is parsed on its own: one that fails to parse is
        reported on stderr and skipped (the rest of its file is still read),
        unless ``strict`` is set. A file that can't be read or tokenized is
        skipped as a whole.

        Returns:
            Tuple of (entities, enums), both keyed by table / type name.

        Raises:
            SqlDependencyError: ``sqlglot`` (``erdify[sql]``) is not installed.
            ModelParseError: ``strict`` is set and at least one file or
                statement failed to parse. Every failure is still reported on
                stderr first.
        """
        try:
            import sqlglot
            from sqlglot import exp
        except ImportError as e:
            raise SqlDependencyError(
                "SQL support requires sqlglot. Install it with: pip install erdify[sql]"
            ) from e

        statements: list[object] = []
        self._parse_errors = []
        for f in self.files:
            try:
                # Read inside the try: an unreadable or non-UTF-8 file is a parse
                # failure for this file only, like a syntax error.
                text = f.read_text(encoding="utf-8")
                dialect = self._dialect = sqlglot.Dialect.get_or_raise(self.dialect)
                tokens = dialect.tokenize(text)
            except Exception as err:
                self._report(f, err)
                continue
            for chunk in _split_statements(tokens, sqlglot.TokenType.SEMICOLON):
                try:
                    statements.extend(self._parse_statement(chunk, text, dialect, exp))
                except Exception as err:
                    self._report(f, err)

        if self.strict and self._parse_errors:
            raise ModelParseError(self._parse_errors)

        for stmt in statements:
            if isinstance(stmt, exp.Create) and (stmt.args.get("kind") or "").upper() == "TABLE":
                self._add_table(stmt, exp)
            elif isinstance(stmt, exp.Create) and (stmt.args.get("kind") or "").upper() == "TYPE":
                self._add_enum(stmt, exp)

        # Second pass: resolve foreign keys (handles forward references + ALTER TABLE)
        # and mark indexed columns.
        for stmt in statements:
            if isinstance(stmt, exp.Create) and (stmt.args.get("kind") or "").upper() == "TABLE":
                self._table_foreign_keys(stmt, exp)
            elif isinstance(stmt, exp.Alter):
                self._alter_foreign_keys(stmt, exp)
            elif isinstance(stmt, exp.Create) and (stmt.args.get("kind") or "").upper() == "INDEX":
                self._mark_index(stmt, exp)

        self._finalize()
        return self._entities, self._enums

    def _report(self, file: Path, err: Exception) -> None:
        print(f"Error parsing {file}: {err}", file=sys.stderr)
        self._parse_errors.append((file, str(err)))

    @staticmethod
    def _parse_statement(tokens: list[Any], text: str, dialect: Any, exp: Any) -> list[object]:
        """Parse one statement's tokens.

        sqlglot parses a ``CREATE TABLE`` it doesn't fully support (e.g. SQLite's
        ``WITHOUT ROWID``) as an opaque ``Command``. The table is then parsed
        again from its head up to the closing parenthesis of the column list,
        so trailing table options it doesn't know are ignored.

        Raises:
            ValueError: the statement is a ``CREATE TABLE`` that can't be read.
        """
        # sqlglot warns when it falls back to a Command; the warning is replayed
        # unless the table is read after all.
        logger = logging.getLogger("sqlglot")
        with _held_warnings(logger) as held:
            parsed = [s for s in dialect.parser().parse(tokens, text) if s is not None]
            head = SqlSchemaParser._table_head(parsed, tokens, text, dialect, exp)
        if head is not None:
            return head
        for record in held:
            logger.handle(record)
        if not (len(parsed) == 1 and isinstance(parsed[0], exp.Command)):
            return parsed
        if SqlSchemaParser._is_plain_create_table(tokens):
            raise ValueError(f"Unsupported CREATE TABLE syntax. Line {tokens[0].line}.")
        return parsed

    @staticmethod
    def _is_plain_create_table(tokens: list[Any]) -> bool:
        """``CREATE [TEMP | TEMPORARY | UNLOGGED | GLOBAL | LOCAL] TABLE ... (``."""
        names = [t.token_type.name for t in tokens]
        head_words = [t.text.upper() for t in tokens[: _index(names, "TABLE")]]
        return (
            names[:1] == ["CREATE"]
            and "TABLE" in names[: _index(names, "L_PAREN")]
            and set(head_words[1:]) <= _TABLE_PREFIXES
        )

    @staticmethod
    def _table_head(
        parsed: list[Any], tokens: list[Any], text: str, dialect: Any, exp: Any
    ) -> list[object] | None:
        """A plain ``CREATE TABLE`` that fell back to a Command, parsed again from
        its head up to the closing parenthesis of its column list, or ``None``."""
        if not (len(parsed) == 1 and isinstance(parsed[0], exp.Command)):
            return None
        if not SqlSchemaParser._is_plain_create_table(tokens):
            return None
        end = _matching_paren([t.token_type.name for t in tokens])
        if end is None:
            return None
        try:
            head = dialect.parser().parse(tokens[: end + 1], text)
        except Exception:
            return None
        if (
            len(head) == 1
            and isinstance(head[0], exp.Create)
            and (head[0].args.get("kind") or "").upper() == "TABLE"
        ):
            return list(head)
        return None

    def _add_table(self, create: "object", exp: "object") -> None:
        """Register a ``CREATE TABLE`` as an entity with its columns (no FKs yet)."""
        schema = create.this  # type: ignore[attr-defined]  # exp.Schema: table + column/constraint expressions
        table_name = schema.this.name
        entity = EntityInfo(name=table_name, table_name=table_name, source="sql")

        coldefs = list(schema.find_all(exp.ColumnDef))  # type: ignore[attr-defined]
        columns = {self._key(c.this): c.name for c in coldefs}
        self._table_keys[self._key(schema.this)] = table_name
        self._column_keys[table_name] = columns
        # Constraint columns name declared columns as the dialect folds names.
        pk_order = [
            name
            for name in (
                _lookup(self._key(i), columns) for i in self._table_level_pk_columns(schema, exp)
            )
            if name is not None
        ]
        pk_cols = set(pk_order)
        unique_cols = {
            _lookup(self._key(i), columns) for i in self._table_level_unique_columns(schema, exp)
        }
        for coldef in coldefs:
            entity.fields.append(self._column(coldef, exp, pk_cols, unique_cols))
        self._entities[table_name] = entity
        self._primary_keys[table_name] = pk_order or [
            f.name for f in entity.fields if f.is_primary_key
        ]

    def _add_enum(self, create: "object", exp: "object") -> None:
        """Register a ``CREATE TYPE ... AS ENUM`` with its string literal values."""
        # stmt.this is an exp.Table node whose .name is the type name
        name_node = create.this  # type: ignore[attr-defined]
        name = name_node.name if name_node is not None else None
        values: list[str] = []
        expr = create.args.get("expression")  # type: ignore[attr-defined]
        if expr is not None:
            for lit in expr.expressions:
                if isinstance(lit, exp.Literal) and lit.is_string:  # type: ignore[attr-defined]
                    values.append(lit.this)
        if name and values:
            self._enums[name] = EnumInfo(name=name, values=values)
            self._enum_keys[self._key(name_node)] = name

    def _column(
        self,
        coldef: "object",
        exp: "object",
        pk_cols: set[str],
        unique_cols: set[str | None],
    ) -> FieldInfo:
        """Build a FieldInfo from a column definition (PK, nullability, default,
        uniqueness); foreign keys are resolved in the second pass."""
        name = coldef.name  # type: ignore[attr-defined]
        kind = coldef.args.get("kind")  # type: ignore[attr-defined]
        type_str = kind.sql().lower() if kind is not None else ""
        type_ref = self._user_defined_type(kind, exp)
        if type_ref is not None:
            prefix, ident = type_ref
            # Unquoted like the CREATE TYPE name: a quoted name keeps its case (#328).
            type_str = prefix + (ident.name if ident.quoted else ident.name.lower())
        constraints = coldef.constraints  # type: ignore[attr-defined]  # list[exp.ColumnConstraint]
        is_pk = name in pk_cols or self._has_constraint(
            constraints,
            exp.PrimaryKeyColumnConstraint,  # type: ignore[attr-defined]
        )
        # sqlglot reads an explicit NULL as NotNullColumnConstraint(allow_null=True).
        not_null = any(
            isinstance(c.kind, exp.NotNullColumnConstraint)  # type: ignore[attr-defined]
            and not c.kind.args.get("allow_null")
            for c in constraints
        )
        default = self._default_value(constraints, exp)
        # Kept as declared: a member of a composite primary key is unique on
        # its own only through UNIQUE; _finalize() clears it on a sole PK (#331).
        is_unique = name in unique_cols or self._has_constraint(
            constraints,
            exp.UniqueColumnConstraint,  # type: ignore[attr-defined]
        )
        field = FieldInfo(
            name=name,
            type_str=type_str,
            is_primary_key=is_pk,
            # A PRIMARY KEY column is implicitly NOT NULL (#217).
            is_nullable=not not_null and not is_pk,
            default_value=default,
            is_unique=is_unique,
        )
        if type_ref is not None:
            self._typed_fields.append((field, type_ref[0], self._key(type_ref[1])))
        return field

    @staticmethod
    def _user_defined_type(kind: Any, exp: Any) -> tuple[str, Any] | None:
        """A user-defined column type (e.g. an enum) as (schema prefix, name
        identifier), or ``None`` for a built-in type.

        Only a dialect that reads quoted type names (PostgreSQL) has the
        identifier; the generic dialect keeps the name as plain text.
        """
        if not isinstance(kind, exp.DataType) or kind.this != exp.DataType.Type.USERDEFINED:
            return None
        ref = kind.args.get("kind")
        if isinstance(ref, exp.Identifier):
            return "", ref
        if isinstance(ref, exp.Dot) and isinstance(ref.expression, exp.Identifier):
            return ref.this.sql().lower().replace('"', "") + ".", ref.expression
        return None

    @staticmethod
    def _has_constraint(constraints: list[object], kind: "type") -> bool:
        """Return True if any column constraint is of the given sqlglot type."""
        return any(isinstance(c.kind, kind) for c in constraints)  # type: ignore[attr-defined]

    @staticmethod
    def _default_value(constraints: list[object], exp: "object") -> str | None:
        """Return the ``DEFAULT`` expression as SQL text, or None."""
        for c in constraints:
            if isinstance(c.kind, exp.DefaultColumnConstraint):  # type: ignore[attr-defined]
                return str(c.kind.this.sql())  # type: ignore[attr-defined]
        return None

    @staticmethod
    def _table_level_pk_columns(schema: "object", exp: "object") -> list[Any]:
        """Return the column identifiers of a table-level ``PRIMARY KEY (...)``, in key order."""
        cols: list[Any] = []
        for pk in schema.find_all(exp.PrimaryKey):  # type: ignore[attr-defined]
            for part in pk.expressions:
                # An Identifier, or a part wrapping one (a Column, an Ordered).
                node = part.find(exp.Identifier)  # type: ignore[attr-defined]
                if node is not None:
                    cols.append(node)
        return cols

    @staticmethod
    def _table_level_unique_columns(schema: "object", exp: "object") -> list[Any]:
        """Return the identifiers of columns covered by a single-column table-level UNIQUE.

        sqlglot represents a table-level ``UNIQUE(col)`` as an
        ``exp.UniqueColumnConstraint`` wrapping a nested ``exp.Schema`` whose
        ``.expressions`` are the column Identifiers. This covers both the
        anonymous form (``UNIQUE (col)``, parent is the table's Schema) and the
        named form (``CONSTRAINT name UNIQUE (col)``, parent is exp.Constraint):
        the constraint's own NAME identifier lives on the parent Constraint
        node, not inside the nested Schema, so it is never mistaken for a
        column. Only single-column constraints are returned — composite
        ``UNIQUE(a, b)`` (anonymous or named) is ignored.
        """
        cols: list[Any] = []
        for uc in schema.find_all(exp.UniqueColumnConstraint):  # type: ignore[attr-defined]
            inner = uc.this
            idents = [
                i
                for i in getattr(inner, "expressions", [])
                if isinstance(i, exp.Identifier)  # type: ignore[attr-defined]
            ]
            if len(idents) == 1:
                cols.append(idents[0])
        return cols

    def _key(self, node: Any) -> str:
        """The name of an identifier (or a Table / Column node) as the dialect folds it.

        Unquoted identifiers are case-insensitive (PostgreSQL folds them to lower
        case); quoted ones keep their case where the dialect does, so
        ``"Account"`` and ``account`` stay two tables in PostgreSQL.
        """
        ident = node if type(node).__name__ == "Identifier" else node.this
        if not hasattr(ident, "copy"):
            return str(ident)
        return str(self._dialect.normalize_identifier(ident.copy()).name)

    def _entity(self, node: Any) -> EntityInfo | None:
        """The table a Table node or identifier names (see :func:`_lookup`)."""
        name = _lookup(self._key(node), self._table_keys)
        return self._entities.get(name) if name is not None else None

    def _set_fks(
        self, entity: EntityInfo, columns: list[Any], ref: "object", exp: "object"
    ) -> None:
        """Mark ``columns`` (identifiers) of ``entity`` as a foreign key per ``REFERENCES``.

        Composite keys pair local and referenced columns in order. No referenced
        columns (a bare ``REFERENCES t``) pairs them with ``t``'s primary key,
        or with ``id`` when ``t`` is unknown. Names are resolved the way the
        dialect resolves them (:meth:`_key`); a target that matches no table is
        kept as written.
        """
        table_node = ref.find(exp.Table)  # type: ignore[attr-defined]
        if table_node is None or not table_node.name:
            return  # unresolved target: never record a bogus ".id"
        target = self._entity(table_node)
        schema_node = ref.this  # type: ignore[attr-defined]
        ref_idents = list(getattr(schema_node, "expressions", None) or [])
        if target is not None:
            target_columns = self._column_keys[target.name]
            ref_cols = [_lookup(self._key(i), target_columns) or i.name for i in ref_idents]
            ref_cols = ref_cols or self._primary_keys.get(target.name, [])
            ref_table = target.name
        else:
            ref_cols = [i.name for i in ref_idents]
            ref_table = table_node.name
        local = self._column_keys[entity.name]
        for i, ident in enumerate(columns):
            rc = ref_cols[i] if i < len(ref_cols) else (ref_cols[0] if ref_cols else "id")
            name = _lookup(self._key(ident), local)
            for f in entity.fields:
                # A column in two foreign keys keeps the first declared one.
                if f.name == name and not f.is_foreign_key:
                    f.is_foreign_key = True
                    f.foreign_table = f"{ref_table}.{rc}"

    def _table_foreign_keys(self, create: "object", exp: "object") -> None:
        """Apply inline ``REFERENCES`` and table-level ``FOREIGN KEY`` clauses."""
        schema = create.this  # type: ignore[attr-defined]
        entity = self._entities.get(schema.this.name)
        if entity is None:
            return
        # Inline REFERENCES on a column definition: exactly one local column.
        for coldef in schema.find_all(exp.ColumnDef):  # type: ignore[attr-defined]
            for c in coldef.constraints:
                ref = c.kind if hasattr(c, "kind") else None
                if isinstance(ref, exp.Reference):  # type: ignore[attr-defined]
                    self._set_fks(entity, [coldef.this], ref, exp)
        self._foreign_key_clauses(entity, schema, exp)

    def _alter_foreign_keys(self, alter: "object", exp: "object") -> None:
        """Apply ``ALTER TABLE ... ADD FOREIGN KEY`` clauses."""
        if alter.this is None:  # type: ignore[attr-defined]
            return
        entity = self._entity(alter.this)  # type: ignore[attr-defined]
        if entity is not None:
            self._foreign_key_clauses(entity, alter, exp)

    def _foreign_key_clauses(self, entity: EntityInfo, node: "object", exp: "object") -> None:
        """Apply every ``FOREIGN KEY (...) REFERENCES t(...)`` below ``node``."""
        for fk in node.find_all(exp.ForeignKey):  # type: ignore[attr-defined]
            cols = [
                e
                for e in fk.expressions
                if isinstance(e, exp.Identifier)  # type: ignore[attr-defined]
            ]
            ref = fk.args.get("reference")
            if ref is not None:
                self._set_fks(entity, cols, ref, exp)

    def _mark_index(self, create: "object", exp: "object") -> None:
        """Mark the columns of a ``CREATE [UNIQUE] INDEX``.

        Each plain column of the index gets ``FieldInfo.index``; an expression
        (``lower(col)``) is not a column. A unique index on one plain column,
        without a ``WHERE`` clause, makes that column unique like a ``UNIQUE``
        constraint (cleared again on a sole primary key, see :meth:`_finalize`).
        """
        index = create.this  # type: ignore[attr-defined]  # exp.Index
        table_node = index.find(exp.Table)  # type: ignore[attr-defined]
        if table_node is None:
            return
        entity = self._entity(table_node)
        if entity is None:
            return
        params = index.args.get("params")
        parts = [
            self._index_part(p, exp)
            for p in (params.args.get("columns") or [] if params is not None else [])
        ]
        columns = self._column_keys[entity.name]
        indexed = {
            _lookup(self._key(p), columns)
            for p in parts
            if isinstance(p, exp.Column)  # type: ignore[attr-defined]
        }
        unique = (
            bool(create.args.get("unique"))  # type: ignore[attr-defined]
            and len(parts) == 1
            and len(indexed) == 1
            and params.args.get("where") is None
        )
        for f in entity.fields:
            if f.name in indexed:
                f.index = True
                if unique:
                    f.is_unique = True

    @staticmethod
    def _index_part(part: Any, exp: "object") -> Any:
        """An index part without its ordering, collation or operator class."""
        while isinstance(part, (exp.Ordered, exp.Collate, exp.Opclass)):  # type: ignore[attr-defined]
            part = part.this
        return part

    def _finalize(self) -> None:
        """Name enum-typed columns' types as their enum, detect link tables,
        then apply ``exclude_patterns``."""
        # Type names fold like table names: `mood` is the enum `Mood` (#328).
        for field, prefix, key in self._typed_fields:
            enum_name = self._enum_keys.get(key)
            if enum_name is not None:
                field.type_str = prefix + enum_name
        for entity in self._entities.values():
            normalize_key_uniqueness(entity.fields)
            entity.is_link_table = is_structural_link_table(entity.fields)
        self._apply_excludes()

    def _apply_excludes(self) -> None:
        """Drop excluded tables and relationships pointing at them."""
        if not self.exclude_patterns:
            return

        def excluded(e: EntityInfo) -> bool:
            return any(
                fnmatchcase(e.name, p) or fnmatchcase(e.table_name, p)
                for p in self.exclude_patterns
            )

        names = {n for n, e in self._entities.items() if excluded(e)}
        self._entities = {n: e for n, e in self._entities.items() if n not in names}
        for e in self._entities.values():
            e.relationships = [r for r in e.relationships if r[0] not in names]
