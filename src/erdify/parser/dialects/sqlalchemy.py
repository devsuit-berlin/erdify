"""SQLModel and SQLAlchemy 2.0 (ORM classes and Core association tables)."""

import ast
from typing import Callable, Dict, Iterable, List, Mapping

from ...config import EntityInfo, FieldInfo, is_structural_link_table
from ..annotations import expr_name, is_call_to, is_mapped_annotation
from .annotated import AnnotatedDialect, extract_foreign_key_arg
from .base import ParseContext


class TableDialect(AnnotatedDialect):
    """Shared by SQLModel and SQLAlchemy: classes mapped to tables.

    An explicit column name (``mapped_column("name")``, ``name=``,
    ``Field(sa_column=Column("name"))``, ``sa_column_kwargs={"name": ...}``)
    names the database column, so the column is drawn under it (#292).
    """

    def __init__(self, ctx: ParseContext):
        super().__init__(ctx)
        #: Table name -> {column key: column name} where an explicit ``key=``
        #: differs from the name (``mapped_column("account_id", key="id")``).
        self._renamed_keys: Dict[str, Dict[str, str]] = {}
        #: id() of foreign-key fields declared with ``link_to_name=True``: their
        #: target already names the column, not its key.
        # Keyed by id() but holding the object, so a freed object's address is
        # never matched by a new one.
        self._name_targets: Dict[int, FieldInfo] = {}
        #: id() of Core tables declared on ``SQLModel.metadata``: they belong
        #: to SQLModel's tables, although they are read as SQLAlchemy.
        self._sqlmodel_core: Dict[int, EntityInfo] = {}

    def _parse_field(self, node: ast.AnnAssign) -> FieldInfo | None:
        """Parse a column, remembering a ``ForeignKey(..., link_to_name=True)``."""
        field = super()._parse_field(node)
        if field is not None and field.is_foreign_key and _links_to_name(node):
            self._name_targets[id(field)] = field
        return field

    def finish(self, entity: EntityInfo, class_node: ast.ClassDef) -> None:
        """Mark ``__table_args__`` uniques, then rename columns to their explicit names."""
        # The unique constraints are matched by attribute name and key first.
        super().finish(entity, class_node)
        keys = self._db_column_names(class_node)
        names = self._db_column_names(class_node, use_key=False)
        renamed = {
            keys[attr]: name for attr, name in names.items() if attr in keys and keys[attr] != name
        }
        if renamed:
            self._renamed_keys[entity.table_name] = renamed
        for f in entity.fields:
            f.name = names.get(f.name, f.name)

    def finalize(self, entities: Mapping[str, EntityInfo]) -> None:
        """Point foreign keys written against a column key at the column's name.

        SQLAlchemy resolves ``ForeignKey("account.id")`` through the column
        key, so with ``mapped_column("account_id", key="id")`` it references
        ``account_id``.
        """
        # Only this dialect's tables: SQLModel and SQLAlchemy keep separate
        # metadata, so a table name may exist in both. A Core table belongs to
        # the metadata it is declared on.
        renamed = self._renamed_keys
        if not renamed:
            return
        sqlmodel_core: Dict[int, EntityInfo] = {}
        name_targets: Dict[int, FieldInfo] = {}
        for dialect in self.ctx.all_dialects():
            if isinstance(dialect, TableDialect):
                sqlmodel_core.update(dialect._sqlmodel_core)
                name_targets.update(dialect._name_targets)
        for entity in entities.values():
            kind = "sqlmodel" if sqlmodel_core.get(id(entity)) is entity else entity.source
            if kind != self.kind:
                continue
            for f in entity.fields:
                if f.foreign_table is None or name_targets.get(id(f)) is f:
                    continue
                table, _, column = f.foreign_table.rpartition(".")
                name = renamed.get(table, {}).get(column)
                if name is not None:
                    f.foreign_table = f"{table}.{name}"


class SQLModelDialect(TableDialect):
    """SQLModel: a class declared with ``table=True``."""

    kind = "sqlmodel"

    def detect(self, class_node: ast.ClassDef) -> bool:
        for keyword in class_node.keywords:
            if keyword.arg == "table" and isinstance(keyword.value, ast.Constant):
                if keyword.value.value:
                    return True
        return False

    def default_table_name(self, class_node: ast.ClassDef) -> str:
        """SQLModel's default ``__tablename__``: the lower-cased class name (#291).

        ``HeroTeam`` -> ``heroteam``, not snake_case; foreign keys written as
        ``foreign_key="heroteam.id"`` must find it.
        """
        return class_node.name.lower()


class SQLAlchemyDialect(TableDialect):
    """SQLAlchemy 2.0: a concrete mapped class has ``__tablename__`` and ``Mapped[...]``.

    Mixins / abstract bases (``Mapped`` fields but no ``__tablename__``) are not
    detected, so they are not emitted as entities, but their fields are still
    inherited.
    """

    kind = "sqlalchemy"
    reads_annotated_columns = True
    plain_value_is_column = False

    def detect(self, class_node: ast.ClassDef) -> bool:
        return has_tablename(class_node) and has_mapped_field(class_node)

    def extra_entities(self, trees: Iterable[ast.Module]) -> List[EntityInfo]:
        """Core association tables (:func:`core_association_tables`, #34)."""
        entities = core_association_tables(trees, self._note_core_table)
        return entities

    def _is_sqlmodel_metadata(self, metadata: ast.expr) -> bool:
        """Whether ``metadata`` is ``SQLModel.metadata``, also through a scanned subclass."""
        if not (isinstance(metadata, ast.Attribute) and metadata.attr == "metadata"):
            return False
        owner = expr_name(metadata.value)
        if owner == "SQLModel":
            return True
        node = self.classes.all.get(owner) if owner is not None else None
        return node is not None and any(
            expr_name(base) == "SQLModel"
            for name in self.classes.dfs_order(node, set())
            for base in self.classes.all[name].bases
        )

    def _note_core_table(self, entity: EntityInfo, call: ast.Call) -> None:
        """Record what the key rewrite needs: the metadata, ``link_to_name`` columns."""
        if len(call.args) > 1 and self._is_sqlmodel_metadata(call.args[1]):
            self._sqlmodel_core[id(entity)] = entity
        columns = {f.name: f for f in entity.fields}
        for arg in call.args:
            if is_call_to(arg, "Column") and arg.args and isinstance(arg.args[0], ast.Constant):
                field = columns.get(str(arg.args[0].value))
                if field is not None and _links_to_name(arg):
                    self._name_targets[id(field)] = field


def core_association_tables(
    trees: Iterable[ast.Module],
    on_table: Callable[[EntityInfo, ast.Call], None] | None = None,
) -> List[EntityInfo]:
    """Link entities from module-level Core ``Table(...)`` assignments.

    ``relationship(secondary=Table(...))`` points at a SQLAlchemy Core table
    rather than a mapped class. Only class definitions become entities in the
    normal passes, so such association tables - and their M:N - would be lost.
    Parse module-level ``name = Table("t", metadata, Column(...), ...)``
    assignments that are structurally association tables (a composite PK
    made up entirely of FK columns) and return them as link entities (#34).
    ``on_table`` is called with each entity and its ``Table(...)`` call.
    """
    entities: List[EntityInfo] = []
    for tree in trees:
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                continue
            if not is_call_to(node.value, "Table"):
                continue

            entity = build_core_table_entity(node.targets[0].id, node.value)
            if entity is not None:
                if on_table is not None:
                    on_table(entity, node.value)
                entities.append(entity)
    return entities


def has_tablename(class_node: ast.ClassDef) -> bool:
    """Check if a class assigns __tablename__ (annotated or plain)."""
    for node in class_node.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "__tablename__":
                return True
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__tablename__":
                    return True
    return False


def has_mapped_field(class_node: ast.ClassDef) -> bool:
    """Check if a class has at least one Mapped[...] annotated field."""
    for node in class_node.body:
        if isinstance(node, ast.AnnAssign) and is_mapped_annotation(node.annotation):
            return True
    return False


def build_core_table_entity(var_name: str, call: ast.Call) -> EntityInfo | None:
    """Build a link EntityInfo from a Core ``Table(...)`` call, or None if it
    is not structurally an association table."""
    # Table name is the first positional string arg; fall back to variable name.
    table_name = var_name
    if call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
        table_name = call.args[0].value

    fields: List[FieldInfo] = []
    for arg in call.args:
        if is_call_to(arg, "Column"):
            field = parse_core_column(arg)
            if field is not None:
                fields.append(field)

    if not is_structural_link_table(fields):
        return None

    entity = EntityInfo(
        name=var_name,
        table_name=table_name,
        base_classes=[],
        source="sqlalchemy",
    )
    entity.fields = fields
    entity.is_link_table = True
    return entity


def parse_core_column(call: ast.Call) -> FieldInfo | None:
    """Parse a Core ``Column("name", <Type>, ForeignKey(...), primary_key=...)``."""
    if not call.args or not isinstance(call.args[0], ast.Constant):
        return None
    col_name = str(call.args[0].value)

    is_primary_key = False
    for keyword in call.keywords:
        if keyword.arg == "primary_key" and isinstance(keyword.value, ast.Constant):
            is_primary_key = bool(keyword.value.value)

    fk_target = extract_foreign_key_arg(call)

    # An optional positional column type (e.g. Column("id", Integer, ...)).
    type_str = ""
    for arg in call.args[1:]:
        if isinstance(arg, ast.Name):
            type_str = arg.id
            break
        if isinstance(arg, ast.Attribute):
            type_str = arg.attr
            break

    return FieldInfo(
        name=col_name,
        type_str=type_str,
        is_primary_key=is_primary_key,
        is_foreign_key=fk_target is not None,
        foreign_table=fk_target,
    )


def _links_to_name(node: ast.AST) -> bool:
    """Whether a ``ForeignKey(..., link_to_name=True)`` appears in the declaration."""
    return any(
        isinstance(sub, ast.expr)
        and is_call_to(sub, "ForeignKey")
        and any(
            kw.arg == "link_to_name"
            and isinstance(kw.value, ast.Constant)
            and kw.value.value is True
            for kw in sub.keywords
        )
        for sub in ast.walk(node)
    )
