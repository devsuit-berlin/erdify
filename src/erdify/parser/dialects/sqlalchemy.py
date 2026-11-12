"""SQLModel and SQLAlchemy 2.0 (ORM classes, classes mapped to Core tables, Core tables)."""

import ast
from typing import Callable, Dict, Iterable, List, Mapping, NamedTuple, Tuple

from ...config import EntityInfo, FieldInfo, is_structural_link_table
from ..annotations import expr_name, is_call_to, is_mapped_annotation
from .annotated import AnnotatedDialect, extract_foreign_key_arg
from .base import Dialect, ParseContext, single_column_uniques


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
    inherited. A class mapped to a Core table, through ``__table__ = Table(...)``
    (#297) or ``registry.map_imperatively(Class, table)`` (#306), is drawn with
    that table's name and columns. Every other module-level Core ``Table(...)``
    is drawn as a table of its own (#34, #305).
    """

    kind = "sqlalchemy"
    reads_annotated_columns = True
    plain_value_is_column = False

    def __init__(self, ctx: ParseContext):
        super().__init__(ctx)
        self._mapped: Dict[str, _MappedTable] | None = None
        #: Entity name -> the ``properties=`` of its ``map_imperatively()`` call.
        self._properties: Dict[str, ast.Dict] = {}
        #: Core columns declared with only a ``ForeignKey``: SQLAlchemy gives
        #: them the referenced column's type.
        self._untyped: List[FieldInfo] = []

    @property
    def _mapped_tables(self) -> Dict[str, "_MappedTable"]:
        """Class name -> the Core table it is mapped to (scanned once per run)."""
        if self._mapped is None:
            self._mapped = mapped_tables(self.ctx.trees, self.classes.all, self.ctx.tree_of)
        return self._mapped

    def detect(self, class_node: ast.ClassDef) -> bool:
        if class_node.name in self._mapped_tables:
            return True
        return has_tablename(class_node) and has_mapped_field(class_node)

    def table_name(self, class_node: ast.ClassDef) -> str | None:
        """The mapped Core table's name, else ``__tablename__``."""
        mapped = self._mapped_tables.get(class_node.name)
        if mapped is not None:
            name = core_table_name(mapped.table)
            if name is not None:
                return name
        return super().table_name(class_node)

    def finish(self, entity: EntityInfo, class_node: ast.ClassDef) -> None:
        """A class mapped to a Core table has exactly that table's columns."""
        mapped = self._mapped_tables.get(class_node.name)
        if mapped is None:
            super().finish(entity, class_node)
            return
        entity.fields = core_table_fields(mapped.table)
        self._note_core_table(entity, mapped.table)
        if mapped.properties is not None:
            self._properties[entity.name] = mapped.properties

    def extra_entities(self, trees: Iterable[ast.Module]) -> List[EntityInfo]:
        """Module-level Core tables no class is mapped to (#34, #305)."""
        mapped = {id(m.table) for m in self._mapped_tables.values()}
        entities: List[EntityInfo] = []
        for tree in trees:
            for var_name, call in module_tables(tree):
                if id(call) in mapped:
                    continue
                entity = build_core_table_entity(var_name, call)
                if entity is not None:
                    self._note_core_table(entity, call)
                    entities.append(entity)
        return entities

    def finalize(self, entities: Mapping[str, EntityInfo]) -> None:
        """Rename keys, type ``ForeignKey``-only Core columns, add imperative relationships."""
        super().finalize(entities)
        columns = {
            f"{entity.table_name}.{f.name}": f
            for entity in entities.values()
            for f in entity.fields
        }
        # A chain of ForeignKey-only columns takes the type from its end.
        changed = True
        while changed:
            changed = False
            for f in self._untyped:
                target = columns.get(f.foreign_table or "")
                if not f.type_str and target is not None and target.type_str:
                    f.type_str = target.type_str
                    changed = True
        for name, properties in self._properties.items():
            entity = entities.get(name)
            if entity is not None:
                self._add_properties(entity, properties, entities)

    def _add_properties(
        self, entity: EntityInfo, properties: ast.Dict, entities: Mapping[str, EntityInfo]
    ) -> None:
        """The ``relationship()`` entries of ``map_imperatively(properties={...})``.

        There is no annotation to read, so the cardinality is inferred the way
        SQLAlchemy does: a foreign key from this table to the target's makes a
        many-to-one, otherwise it is one-to-many (``uselist=False``: one-to-one).
        """
        for key, value in zip(properties.keys, properties.values):
            if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                continue
            if not is_call_to(value, "relationship") or not isinstance(value, ast.Call):
                continue
            # A secondary= many-to-many is drawn through its association table.
            if any(kw.arg == "secondary" for kw in value.keywords):
                continue
            target = _relationship_target(value)
            if target is None:
                continue
            options = {kw.arg: kw.value for kw in value.keywords if kw.arg}
            uselist = options.get("uselist")
            target_entity = entities.get(target)
            if target == entity.name:
                # Self-referential: one-to-many unless remote_side= turns it around.
                references: List[FieldInfo] = (
                    [f for f in entity.fields if f.is_foreign_key]
                    if "remote_side" in options
                    else []
                )
            elif target_entity is not None:
                prefix = f"{target_entity.table_name}."
                references = [
                    f
                    for f in entity.fields
                    if f.is_foreign_key and (f.foreign_table or "").startswith(prefix)
                ]
            else:
                references = []
            if references:
                kind, nullable = "one", any(f.is_nullable for f in references)
            else:
                to_one = isinstance(uselist, ast.Constant) and uselist.value is False
                kind, nullable = ("one", True) if to_one else ("many", False)
            entity.relationships.append((target, kind, key.value))
            if nullable:
                entity.nullable_relationships.append(key.value)
            inverse = self._back_populates(value)
            if inverse is not None:
                entity.inverse_relationships[key.value] = inverse

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
        """Record what :meth:`finalize` needs: the metadata, keys, ``link_to_name``, types."""
        owner: TableDialect = self
        if len(call.args) > 1 and self._is_sqlmodel_metadata(call.args[1]):
            self._sqlmodel_core[id(entity)] = entity
            owner = next(d for d in self.ctx.all_dialects() if isinstance(d, SQLModelDialect))
        columns = {f.name: f for f in entity.fields}
        renamed: Dict[str, str] = {}
        for arg in call.args:
            if not is_call_to(arg, "Column") or not isinstance(arg, ast.Call):
                continue
            name = self._explicit_column_name(arg, use_key=False)
            key = self._explicit_column_name(arg)
            field = columns.get(name or "")
            if field is None:
                continue
            if key is not None and key != name:
                renamed[key] = field.name
            if _links_to_name(arg):
                self._name_targets[id(field)] = field
            if field.is_foreign_key and not field.type_str:
                self._untyped.append(field)
        if renamed:
            owner._renamed_keys.setdefault(entity.table_name, {}).update(renamed)


class _MappedTable(NamedTuple):
    """The Core table a class is mapped to."""

    table: ast.Call
    #: ``map_imperatively(..., properties={...})``, if given as a dict literal.
    properties: ast.Dict | None = None


def module_tables(tree: ast.Module) -> List[Tuple[str, ast.Call]]:
    """``(variable, call)`` for each module-level ``name = Table(...)``, in source order."""
    found: List[Tuple[str, ast.Call]] = []
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Call)
            and is_call_to(node.value, "Table")
        ):
            found.append((node.targets[0].id, node.value))
    return found


def mapped_tables(
    trees: Iterable[ast.Module],
    classes: Mapping[str, ast.ClassDef],
    tree_of: Callable[[ast.ClassDef], ast.Module | None],
) -> Dict[str, _MappedTable]:
    """Classes mapped to a Core table, by class name.

    ``class X(Base): __table__ = Table(...)`` (or a module-level table
    variable, #297), and ``registry.map_imperatively(X, table, properties=...)``
    anywhere in a scanned file, e.g. inside a ``start_mappers()`` function (#306).
    A table variable is looked up in the same file first, then in every
    scanned file.
    """
    trees = list(trees)
    per_tree = {id(tree): dict(module_tables(tree)) for tree in trees}
    everywhere: Dict[str, ast.Call] = {}
    for tree in trees:
        for name, call in per_tree[id(tree)].items():
            everywhere.setdefault(name, call)

    def resolve(value: ast.expr | None, tree: ast.Module | None) -> ast.Call | None:
        if isinstance(value, ast.Call) and is_call_to(value, "Table"):
            return value
        if isinstance(value, ast.Name):
            local = per_tree.get(id(tree), {}) if tree is not None else {}
            return local.get(value.id) or everywhere.get(value.id)
        return None

    found: Dict[str, _MappedTable] = {}
    for name, class_node in classes.items():
        for node in class_node.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "__table__" for t in node.targets
            ):
                table = resolve(node.value, tree_of(class_node))
                if table is not None:
                    found[name] = _MappedTable(table)
    for tree in trees:
        for mapping in ast.walk(tree):
            if not (
                isinstance(mapping, ast.Call)
                and isinstance(mapping.func, ast.Attribute)
                and mapping.func.attr == "map_imperatively"
                and mapping.args
                and isinstance(mapping.args[0], ast.Name)
                and mapping.args[0].id in classes
            ):
                continue
            options = {kw.arg: kw.value for kw in mapping.keywords if kw.arg}
            table = resolve(
                mapping.args[1] if len(mapping.args) > 1 else options.get("local_table"), tree
            )
            if table is None:
                continue  # e.g. single-table inheritance: no table of its own
            properties = options.get("properties")
            found[mapping.args[0].id] = _MappedTable(
                table, properties if isinstance(properties, ast.Dict) else None
            )
    return found


def _relationship_target(call: ast.Call) -> str | None:
    """The class ``relationship(Target)`` points at: a name, ``"Target"`` or a lambda."""
    target: ast.expr | None = call.args[0] if call.args else None
    for kw in call.keywords:
        if kw.arg == "argument":
            target = kw.value
    if isinstance(target, ast.Lambda):
        target = target.body
    if isinstance(target, ast.Constant) and isinstance(target.value, str):
        return target.value.rpartition(".")[2]
    if isinstance(target, (ast.Name, ast.Attribute)):
        return expr_name(target)
    return None


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


def core_table_name(call: ast.Call) -> str | None:
    """The name of a Core ``Table("name", metadata, ...)``."""
    if call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
        return call.args[0].value
    for kw in call.keywords:
        if kw.arg == "name" and isinstance(kw.value, ast.Constant):
            return str(kw.value.value)
    return None


def build_core_table_entity(var_name: str, call: ast.Call) -> EntityInfo | None:
    """An entity for a module-level Core ``Table(...)``, keyed by its variable.

    None for a table without readable columns (e.g. a reflected
    ``Table("t", metadata, autoload_with=engine)``). A table that is
    structurally an association table is a link entity (#34).
    """
    fields = core_table_fields(call)
    if not fields:
        return None
    entity = EntityInfo(
        name=var_name,
        table_name=core_table_name(call) or var_name,
        base_classes=[],
        source="sqlalchemy",
    )
    entity.fields = fields
    entity.is_link_table = is_structural_link_table(fields)
    return entity


def core_table_fields(call: ast.Call) -> List[FieldInfo]:
    """The columns of a Core ``Table(...)``, with its table-level constraints applied.

    Reads ``Column(...)`` arguments and single-column ``PrimaryKeyConstraint``,
    ``ForeignKeyConstraint``, ``UniqueConstraint`` and unique ``Index`` ones.
    """
    fields: List[FieldInfo] = []
    # Constraints name a column through its key (``key=``, else the name).
    by_name: Dict[str, FieldInfo] = {}
    for arg in call.args:
        if is_call_to(arg, "Column") and isinstance(arg, ast.Call):
            field = parse_core_column(arg)
            if field is not None:
                fields.append(field)
                by_name[Dialect._explicit_column_name(arg) or field.name] = field
    for arg in call.args:
        if not isinstance(arg, ast.Call):
            continue
        if is_call_to(arg, "PrimaryKeyConstraint"):
            for name in _strings(arg.args):
                if name in by_name:
                    by_name[name].is_primary_key = True
        elif is_call_to(arg, "ForeignKeyConstraint") and len(arg.args) >= 2:
            columns, targets = _strings_of(arg.args[0]), _strings_of(arg.args[1])
            if len(columns) == 1 and len(targets) == 1 and columns[0] in by_name:
                by_name[columns[0]].is_foreign_key = True
                by_name[columns[0]].foreign_table = targets[0]
    unique, _ = single_column_uniques(call.args)
    for key in unique:
        if key in by_name:
            by_name[key].is_unique = True
    for f in fields:
        if f.is_primary_key:
            f.is_nullable = False  # a primary key is never NULL
            f.is_unique = False
    return fields


def parse_core_column(call: ast.Call) -> FieldInfo | None:
    """Parse a Core ``Column("name", <Type>, ForeignKey(...), primary_key=...)``.

    As in SQLAlchemy, a column is nullable unless it is a primary key or says
    ``nullable=False``.
    """
    col_name = Dialect._explicit_column_name(call, use_key=False)
    if col_name is None:
        return None
    options = {kw.arg: kw.value for kw in call.keywords if kw.arg}

    def flag(name: str) -> bool | None:
        value = options.get(name)
        if isinstance(value, ast.Constant) and isinstance(value.value, bool):
            return value.value
        return None

    is_primary_key = bool(flag("primary_key"))
    nullable = flag("nullable")
    fk_target = extract_foreign_key_arg(call)

    # The column type: type_=, else the first positional argument (after the
    # name) that is not a schema item such as ForeignKey(...).
    positional = call.args[1:] if isinstance(call.args[0], ast.Constant) else list(call.args)
    candidates = [options["type_"]] if "type_" in options else positional
    type_str = ""
    for arg in candidates:
        type_str = _core_type(arg)
        if type_str:
            break

    default = options.get("default")
    default_value = None
    if isinstance(default, ast.Constant):
        default_value = repr(default.value)
    elif isinstance(default, ast.Attribute) and isinstance(default.value, ast.Name):
        default_value = f"{default.value.id}.{default.attr}"

    return FieldInfo(
        name=col_name,
        type_str=type_str,
        is_primary_key=is_primary_key,
        is_foreign_key=fk_target is not None,
        is_nullable=(not is_primary_key) if nullable is None else nullable and not is_primary_key,
        foreign_table=fk_target,
        index=bool(flag("index")),
        default_value=default_value,
        is_unique=bool(flag("unique")) and not is_primary_key,
    )


def _core_type(arg: ast.expr) -> str:
    """The Python type a ``Column()`` type argument maps to, as ORM columns show it.

    ``Integer`` / ``String(50)`` -> ``int`` / ``str``, ``Enum(Status)`` ->
    ``Status``; another type keeps its name. Empty for a schema item such as
    ``ForeignKey(...)`` (not a type).
    """
    call = arg if isinstance(arg, ast.Call) else None
    name = expr_name(call.func if call is not None else arg)
    if name is None:
        return ""
    name = name.rpartition(".")[2]
    if name in _SCHEMA_ITEMS:
        return ""
    if name == "Enum" and call is not None and call.args:
        enum_class = expr_name(call.args[0])
        if enum_class is not None:
            return enum_class.rpartition(".")[2]
    return _PYTHON_TYPES.get(name, name)


#: SQLAlchemy column types -> the Python type of their values.
_PYTHON_TYPES = {
    **dict.fromkeys(
        ("Integer", "SmallInteger", "BigInteger", "INTEGER", "INT", "SMALLINT", "BIGINT"), "int"
    ),
    **dict.fromkeys(
        (
            "String",
            "Text",
            "Unicode",
            "UnicodeText",
            "VARCHAR",
            "NVARCHAR",
            "CHAR",
            "NCHAR",
            "TEXT",
            "CLOB",
        ),
        "str",
    ),
    **dict.fromkeys(("Boolean", "BOOLEAN"), "bool"),
    **dict.fromkeys(("Float", "Double", "REAL", "FLOAT", "DOUBLE", "DOUBLE_PRECISION"), "float"),
    **dict.fromkeys(("Numeric", "NUMERIC", "DECIMAL"), "Decimal"),
    **dict.fromkeys(("DateTime", "DATETIME", "TIMESTAMP"), "datetime"),
    **dict.fromkeys(("Date", "DATE"), "date"),
    **dict.fromkeys(("Time", "TIME"), "time"),
    "Interval": "timedelta",
    **dict.fromkeys(("LargeBinary", "BLOB", "BINARY", "VARBINARY"), "bytes"),
    **dict.fromkeys(("Uuid", "UUID"), "UUID"),
    **dict.fromkeys(("JSON", "JSONB"), "dict"),
}

#: Positional ``Column()`` arguments that are not its type.
_SCHEMA_ITEMS = frozenset(
    {
        "ForeignKey",
        "Sequence",
        "Identity",
        "Computed",
        "FetchedValue",
        "DefaultClause",
        "CheckConstraint",
    }
)


def _strings(args: Iterable[ast.expr]) -> List[str]:
    """The string constants among ``args``."""
    return [a.value for a in args if isinstance(a, ast.Constant) and isinstance(a.value, str)]


def _strings_of(value: ast.expr) -> List[str]:
    """The strings of a list / tuple literal (``["a", "b"]``)."""
    return _strings(value.elts) if isinstance(value, (ast.List, ast.Tuple)) else []


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
