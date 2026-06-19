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
        except ImportError as e:
            raise SqlDependencyError(
                "SQL support requires sqlglot. Install it with: pip install erdify[sql]"
            ) from e

        statements = []
        for f in self.files:
            text = f.read_text()
            try:
                statements.extend(sqlglot.parse(text, dialect=self.dialect))
            except Exception as err:
                print(f"Error parsing {f}: {err}", file=sys.stderr)

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
        return self.entities, self.enums

    def _add_table(self, create: "object", exp: "object") -> None:
        schema = create.this  # type: ignore[attr-defined]  # exp.Schema: table + column/constraint expressions
        table_name = schema.this.name
        entity = EntityInfo(name=table_name, table_name=table_name, source="sql")

        pk_cols = self._table_level_pk_columns(schema, exp)
        for coldef in schema.find_all(exp.ColumnDef):  # type: ignore[attr-defined]
            entity.fields.append(self._column(coldef, exp, pk_cols))
        self.entities[table_name] = entity

    def _add_enum(self, create: "object", exp: "object") -> None:
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
            self.enums[name] = EnumInfo(name=name, values=values)

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

    def _set_fk(self, table: str, column: str, ref_table: str, ref_col: str) -> None:
        if not ref_table:
            return
        entity = self.entities.get(table)
        if entity is None:
            return
        for f in entity.fields:
            if f.name == column:
                f.is_foreign_key = True
                f.foreign_table = f"{ref_table}.{ref_col or 'id'}"
                return

    def _table_foreign_keys(self, create: "object", exp: "object") -> None:
        schema = create.this  # type: ignore[attr-defined]
        table = schema.this.name
        # Inline REFERENCES on a column definition.
        for coldef in schema.find_all(exp.ColumnDef):  # type: ignore[attr-defined]
            for c in coldef.constraints:
                ref = c.kind if hasattr(c, "kind") else None
                if isinstance(ref, exp.Reference):  # type: ignore[attr-defined]
                    rt, rcs = self._reference_target_multi(ref, exp)
                    # Inline REFERENCES always has exactly one local column.
                    self._set_fk(table, coldef.name, rt, rcs[0] if rcs else "id")
        # Table-level FOREIGN KEY (...) REFERENCES t(c1, c2, ...).
        for fk in schema.find_all(exp.ForeignKey):  # type: ignore[attr-defined]
            cols = [
                e.name
                for e in fk.expressions
                if isinstance(e, exp.Identifier)  # type: ignore[attr-defined]
            ]
            ref = fk.args.get("reference")
            if ref is not None:
                rt, rcs = self._reference_target_multi(ref, exp)
            else:
                rt, rcs = "", []
            for i, col in enumerate(cols):
                rc = rcs[i] if i < len(rcs) else (rcs[0] if rcs else "id")
                self._set_fk(table, col, rt, rc)

    def _alter_foreign_keys(self, alter: "object", exp: "object") -> None:
        table = alter.this.name if alter.this is not None else ""  # type: ignore[attr-defined]
        for fk in alter.find_all(exp.ForeignKey):  # type: ignore[attr-defined]
            cols = [
                e.name
                for e in fk.expressions
                if isinstance(e, exp.Identifier)  # type: ignore[attr-defined]
            ]
            ref = fk.args.get("reference")
            if ref is not None:
                rt, rcs = self._reference_target_multi(ref, exp)
            else:
                rt, rcs = "", []
            for i, col in enumerate(cols):
                rc = rcs[i] if i < len(rcs) else (rcs[0] if rcs else "id")
                self._set_fk(table, col, rt, rc)

    @staticmethod
    def _reference_target_multi(ref: "object", exp: "object") -> tuple[str, list[str]]:
        """Extract (ref_table_name, [ref_col_names]) from an exp.Reference node.

        The Reference wraps a Schema whose .this is the target Table and whose
        .expressions are the referenced column Identifiers.  Using
        schema.expressions avoids the ambiguity of find_all(Identifier) which
        also returns the table-name identifier.

        Returns all referenced columns so callers can pair them positionally with
        local FK columns (composite FK support). Falls back to ["id"] when no
        explicit columns are listed (bare REFERENCES t with no column list).
        """
        table_node = ref.find(exp.Table)  # type: ignore[attr-defined]
        ref_table = table_node.name if table_node is not None else ""
        schema_node = ref.this  # type: ignore[attr-defined]
        if hasattr(schema_node, "expressions") and schema_node.expressions:
            ref_cols = [e.name for e in schema_node.expressions]
        else:
            ref_cols = ["id"]
        return ref_table, ref_cols

    def _mark_index(self, create: "object", exp: "object") -> None:
        """Set FieldInfo.index=True for columns covered by a CREATE INDEX statement."""
        index = create.this  # type: ignore[attr-defined]  # exp.Index
        table_node = index.find(exp.Table)  # type: ignore[attr-defined]
        if table_node is None:
            return
        entity = self.entities.get(table_node.name)
        if entity is None:
            return
        indexed = {c.name for c in index.find_all(exp.Column)}  # type: ignore[attr-defined]
        for f in entity.fields:
            if f.name in indexed:
                f.index = True

    @staticmethod
    def _is_structural_link_table(fields: list[FieldInfo]) -> bool:
        if len(fields) != 2:
            return False
        return all(f.is_foreign_key and f.is_primary_key for f in fields)

    def _finalize(self) -> None:
        for entity in self.entities.values():
            entity.is_link_table = self._is_structural_link_table(entity.fields)
        self._apply_excludes()

    def _apply_excludes(self) -> None:
        if not self.exclude_patterns:
            return

        def excluded(e: EntityInfo) -> bool:
            return any(
                fnmatchcase(e.name, p) or fnmatchcase(e.table_name, p)
                for p in self.exclude_patterns
            )

        names = {n for n, e in self.entities.items() if excluded(e)}
        self.entities = {n: e for n, e in self.entities.items() if n not in names}
        for e in self.entities.values():
            e.relationships = [r for r in e.relationships if r[0] not in names]
