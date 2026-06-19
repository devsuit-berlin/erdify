"""SQL DDL frontend for erdify (optional, requires the `sql` extra: sqlglot)."""

import os
import sys
from fnmatch import fnmatchcase
from pathlib import Path

from .config import EntityInfo, EnumInfo, FieldInfo
from .parser import DEFAULT_EXCLUDE_DIRS, _match_include


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


class SqlDependencyError(RuntimeError):
    """Raised when SQL parsing is requested without the optional sqlglot dep."""


class SqlSchemaParser:
    """Parse SQL DDL files into erdify's IR using sqlglot (lazy-imported)."""

    def __init__(
        self,
        files: list[Path],
        dialect: str | None = None,
        exclude_patterns: list[str] | None = None,
    ):
        self.files = files
        self.dialect = dialect
        self.exclude_patterns = exclude_patterns or []
        self.entities: dict[str, EntityInfo] = {}
        self.enums: dict[str, EnumInfo] = {}

    def parse(self) -> tuple[dict[str, EntityInfo], dict[str, EnumInfo]]:
        try:
            import sqlglot
            from sqlglot import exp
        except ImportError as e:  # pragma: no cover - exercised via monkeypatch in tests
            raise SqlDependencyError(
                "SQL support requires sqlglot. Install it with: pip install erdify[sql]"
            ) from e

        statements = []
        for f in self.files:
            text = f.read_text()
            try:
                statements.extend(sqlglot.parse(text, dialect=self.dialect or None))
            except Exception as err:
                print(f"Error parsing {f}: {err}", file=sys.stderr)

        for stmt in statements:
            if isinstance(stmt, exp.Create) and (stmt.args.get("kind") or "").upper() == "TABLE":
                self._add_table(stmt, exp)
        # Foreign keys + enums + indexes are resolved in later tasks (Task 4/5/6).
        self._finalize()
        return self.entities, self.enums

    def _add_table(self, create: "object", exp: "object") -> None:
        schema = create.this  # type: ignore[attr-defined]  # exp.Schema: table + column/constraint expressions
        table_name = schema.this.name
        entity = EntityInfo(name=table_name, table_name=table_name, source="sql")

        pk_cols = self._table_level_pk_columns(schema, exp)
        for coldef in schema.find_all(exp.ColumnDef):  # type: ignore[attr-defined]
            entity.fields.append(self._column(coldef, exp, pk_cols))
        self.entities[table_name] = entity

    def _column(self, coldef: "object", exp: "object", pk_cols: set[str]) -> FieldInfo:
        name = coldef.name  # type: ignore[attr-defined]
        kind = coldef.args.get("kind")  # type: ignore[attr-defined]
        type_str = kind.sql().lower() if kind is not None else ""
        constraints = coldef.constraints  # type: ignore[attr-defined]  # list[exp.ColumnConstraint]
        is_pk = name in pk_cols or self._has_constraint(
            constraints,
            exp.PrimaryKeyColumnConstraint,  # type: ignore[attr-defined]
        )
        not_null = self._has_constraint(
            constraints,
            exp.NotNullColumnConstraint,  # type: ignore[attr-defined]
        )
        default = self._default_value(constraints, exp)
        return FieldInfo(
            name=name,
            type_str=type_str,
            is_primary_key=is_pk,
            is_nullable=not not_null,
            default_value=default,
        )

    @staticmethod
    def _has_constraint(constraints: list[object], kind: "type") -> bool:
        return any(isinstance(c.kind, kind) for c in constraints)  # type: ignore[attr-defined]

    @staticmethod
    def _default_value(constraints: list[object], exp: "object") -> str | None:
        for c in constraints:
            if isinstance(c.kind, exp.DefaultColumnConstraint):  # type: ignore[attr-defined]
                return str(c.kind.this.sql())  # type: ignore[attr-defined]
        return None

    @staticmethod
    def _table_level_pk_columns(schema: "object", exp: "object") -> set[str]:
        cols: set[str] = set()
        for pk in schema.find_all(exp.PrimaryKey):  # type: ignore[attr-defined]
            for col in pk.find_all(exp.Column):  # type: ignore[attr-defined]
                cols.add(col.name)
            for ident in pk.expressions:
                if isinstance(ident, exp.Identifier):  # type: ignore[attr-defined]
                    cols.add(ident.name)
        return cols

    def _finalize(self) -> None:
        # Link-table flag + exclude patterns are applied here; filled in Task 4.
        pass
