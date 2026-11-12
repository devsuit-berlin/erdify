"""SQLModel and SQLAlchemy 2.0 (ORM classes, classes mapped to Core tables, Core tables)."""

import ast
from typing import Callable, Dict, Iterable, List, Mapping, NamedTuple, Set, Tuple

from ...config import EntityInfo, FieldInfo, is_structural_link_table
from ..annotations import column_type, expr_name, is_call_to, is_mapped_annotation
from ..common import _Rel
from .annotated import AnnotatedDialect, extract_foreign_key_arg
from .base import ParseContext, explicit_column_name, single_column_uniques


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
        self._optional_reverse_references(entities)
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

    def _optional_reverse_references(self, entities: Mapping[str, EntityInfo]) -> None:
        """Mark a to-one reference from the referenced side as optional (#299).

        SQLAlchemy makes a relationship many-to-one only when the foreign key
        to the target is in the class's own table (or a mapped parent's);
        otherwise it is the reverse of a one-to-one (``uselist=False``), and
        nothing in the database forces the other row to exist, whatever the
        annotation says. A self-referential reference keeps its annotation:
        its direction depends on ``remote_side=``.
        """
        for entity in entities.values():
            if entity.source != self.kind:
                continue
            local_tables: Set[str] | None = None
            for target, kind, attr in entity.relationships:
                if kind != "one" or attr in entity.nullable_relationships:
                    continue
                target_entity = entities.get(target)
                if target_entity is None or target == entity.name:
                    continue
                if local_tables is None:
                    local_tables = self._referenced_tables(entity, entities)
                if target_entity.table_name not in local_tables:
                    entity.nullable_relationships.append(attr)

    def _referenced_tables(
        self, entity: EntityInfo, entities: Mapping[str, EntityInfo]
    ) -> Set[str]:
        """Tables the foreign keys of an entity's table and its mapped parents' reference."""
        class_node = self.classes.all.get(entity.name)
        names = (
            self.classes.dfs_order(class_node, set()) if class_node is not None else [entity.name]
        )
        return {
            f.foreign_table.rpartition(".")[0]
            for name in names
            for owner in [entities.get(name)]
            if owner is not None and owner.source == entity.source
            for f in owner.fields
            if f.foreign_table
        }


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

    def member_nodes(self, class_node: ast.ClassDef) -> List[ast.AnnAssign]:
        """Annotated attributes, with a ``Field()`` from ``Annotated`` metadata applied (#295)."""
        return [_with_metadata_field(node) for node in super().member_nodes(class_node)]


def _with_metadata_field(node: ast.AnnAssign) -> ast.AnnAssign:
    """``node`` as SQLModel 0.0.32+ reads a ``Field()`` in its ``Annotated`` metadata (#295).

    ``x: Annotated[str, Field(unique=True)] = "a"`` maps like ``x: str =
    Field("a", unique=True)``: the first ``Field()`` of a top-level
    ``Annotated`` applies, with an assigned plain value as its default. An
    assigned ``Field()`` replaces it entirely. Older SQLModel releases ignore
    it.
    """
    if node.value is not None and is_call_to(node.value, "Field"):
        return node
    field = next(
        (
            item
            for item in _annotated_metadata(node.annotation)
            if is_call_to(item, "Field") and not _is_pydantic_field(item)
        ),
        None,
    )
    if field is None:
        return node
    if node.value is not None:
        keywords = [kw for kw in field.keywords if kw.arg not in ("default", "default_factory")]
        field = ast.Call(
            func=field.func, args=[], keywords=[*keywords, ast.keyword("default", node.value)]
        )
    member = ast.AnnAssign(
        target=node.target, annotation=node.annotation, value=field, simple=node.simple
    )
    return ast.copy_location(member, node)


def _annotated_metadata(annotation: ast.expr) -> List[ast.expr]:
    """The metadata of a top-level ``Annotated[...]``, nested ones flattened innermost first."""
    if not isinstance(annotation, ast.Subscript) or expr_name(annotation.value) != "Annotated":
        return []
    items = annotation.slice.elts if isinstance(annotation.slice, ast.Tuple) else []
    if not items:
        return []
    return [*_annotated_metadata(items[0]), *items[1:]]


def _is_pydantic_field(call: ast.Call) -> bool:
    """``pydantic.Field(...)``: it carries no SQLModel column settings."""
    func = call.func
    return isinstance(func, ast.Attribute) and expr_name(func.value) == "pydantic"


class SQLAlchemyDialect(TableDialect):
    """SQLAlchemy 2.0: a concrete mapped class has ``__tablename__`` and ``Mapped[...]``.

    Mixins / abstract bases (``Mapped`` fields but no ``__tablename__``) are not
    detected, so they are not emitted as entities, but their fields are still
    inherited. A mapped parent's columns stay in its own table: a joined-table
    subclass (``__tablename__`` of its own) gets only its own columns, and a
    single-table subclass (none, or ``__tablename__ = None``) is not drawn and
    adds its columns to the parent's table (#293, #302). A class mapped to a
    Core table, through ``__table__ = Table(...)``
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
        self._untyped: List[Tuple[FieldInfo, str]] = []
        #: Table-owning class -> its single-table subclasses (#302).
        self._single: Dict[str, List[str]] | None = None
        #: id() of each parsed column -> (the column, its annotation's
        #: nullability, before an explicit ``nullable=``).
        self._annotation_nullable: Dict[int, Tuple[FieldInfo, bool]] = {}

    @property
    def _mapped_tables(self) -> Dict[str, "_MappedTable"]:
        """Class name -> the Core table it is mapped to (scanned once per run)."""
        if self._mapped is None:
            self._mapped = mapped_tables(self.ctx.trees, self.classes.all, self.ctx.tree_of)
        return self._mapped

    def detect(self, class_node: ast.ClassDef) -> bool:
        if class_node.name in self._mapped_tables:
            return True
        if _sets_true(class_node, "__abstract__"):
            return False  # never mapped; SQLAlchemy ignores its __tablename__
        return has_tablename(class_node) and has_mapped_field(class_node)

    def table_name(self, class_node: ast.ClassDef) -> str | None:
        """The mapped Core table's name, else ``__tablename__``."""
        mapped = self._mapped_tables.get(class_node.name)
        if mapped is not None:
            name = core_table_name(mapped.table)
            if name is not None:
                return name
        return super().table_name(class_node)

    def _parse_field(self, node: ast.AnnAssign) -> FieldInfo | None:
        """Parse a column, remembering the nullability its annotation alone gives."""
        field = super()._parse_field(node)
        if field is not None:
            self._annotation_nullable[id(field)] = (field, column_type(node.annotation)[1])
        return field

    def member_nodes(self, class_node: ast.ClassDef) -> List[ast.AnnAssign]:
        """Annotated attributes, and ``@declared_attr`` methods read as one (#298).

        SQLAlchemy only accepts a relationship on a mixin through
        ``@declared_attr``: ``def owner(cls) -> Mapped["Owner"]: return
        relationship(...)`` maps ``owner`` like ``owner: Mapped["Owner"] =
        relationship(...)``.
        """
        members: List[ast.AnnAssign] = []
        for node in class_node.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                members.append(node)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                member = declared_attr_member(node)
                if member is not None:
                    members.append(member)
        return members

    # -- mapped-class inheritance (#293, #302) ----------------------------------

    def _is_single_table(self, class_node: ast.ClassDef) -> bool:
        """A subclass of a mapped class without a table of its own (#302).

        SQLAlchemy maps every subclass of a mapped class; without
        ``__tablename__`` / ``__table__`` (and not ``__abstract__``) it is
        stored in its parent's table.
        """
        if (
            self.detect(class_node)
            or has_tablename(class_node)
            or _sets_true(class_node, "__abstract__")
            or _assigns(class_node, "__table__")  # one erdify could not resolve
            or self._tablename_is_function(class_node.name)
        ):
            return False
        return self._table_owner(class_node.name) is not None

    def _ancestors(self, name: str) -> List[str]:
        """The ancestors of class ``name``, nearest first (its MRO without itself)."""
        node = self.classes.all[name]
        order = self.classes.mro(name) or self.classes.dfs_order(node, set())[::-1]
        return [a for a in order if a != name]

    def _tablename_is_function(self, name: str) -> bool:
        """Whether the ``__tablename__`` of class ``name`` is a ``@declared_attr``.

        Its own or inherited, whichever the MRO finds first. It names a table
        of the class's own, which erdify can't read.
        """
        for ancestor in [name, *self._ancestors(name)]:
            node = self.classes.all[ancestor]
            if _defines_function(node, "__tablename__"):
                return True
            if _assigns(node, "__tablename__"):
                return False
        return False

    def _table_owner(self, name: str) -> str | None:
        """The nearest ancestor of class ``name`` with a table, if erdify draws it.

        A class mapped with ``map_imperatively()`` owns no subclass columns: an
        imperative mapping maps only its table's columns, never annotations.
        An ancestor whose table erdify can't read (a ``@declared_attr`` table
        name, an unresolved ``__table__``) ends the search: no owner.
        """
        for ancestor in self._ancestors(name):
            node = self.classes.all[ancestor]
            if _sets_true(node, "__abstract__"):
                continue  # not mapped; SQLAlchemy ignores its __tablename__
            if self._tablename_is_function(ancestor) and any(
                self.detect(self.classes.all[a]) for a in self._ancestors(ancestor)
            ):
                return None  # a mapped subclass with a computed table, not a mixin
            mapped = self._mapped_tables.get(ancestor)
            if mapped is not None and mapped.imperative:
                return None
            if mapped is None and _assigns(node, "__table__"):
                return None  # a table erdify could not resolve
            if has_tablename(node) or mapped is not None:
                return ancestor if self.detect(node) else None
        return None

    @property
    def _single_table_subclasses(self) -> Dict[str, List[str]]:
        """Table-owning class name -> its single-table subclasses, in mapping order.

        Source order, except that a subclass declared before its single-table
        parent (in another file) comes after it, as SQLAlchemy maps them.
        """
        if self._single is None:
            self._single = {}
            for name, node in self.classes.all.items():
                owner = self._table_owner(name) if self._is_single_table(node) else None
                if owner is not None:
                    self._single.setdefault(owner, []).append(name)
            for owner, subs in self._single.items():
                self._single[owner] = self._parents_first(subs)
        return self._single

    def _parents_first(self, subs: List[str]) -> List[str]:
        """``subs`` in source order, each moved after the ones it inherits from."""
        members = set(subs)
        ordered: List[str] = []

        def visit(name: str) -> None:
            if name in ordered:
                return
            for ancestor in reversed(self._ancestors(name)):
                if ancestor in members:
                    visit(ancestor)
            ordered.append(name)

        for sub in subs:
            visit(sub)
        return ordered

    def table_classes(self, class_node: ast.ClassDef, names: List[str]) -> Set[str]:
        """Leave out each mapped ancestor and its bases: they have a table of their own (#293).

        A joined-table subclass gets only the columns of its own body and of
        the mixins that only it inherits; a single-table subclass, read for
        its parent's table, likewise only adds its own.
        """
        excluded = self._mapped_ancestry(class_node, names)
        return {name for name in names if name not in excluded}

    def _mapped_ancestry(self, class_node: ast.ClassDef, names: List[str]) -> Set[str]:
        """The mapped ancestors among ``names`` and their bases: stored in another table."""
        excluded: Set[str] = set()
        for name in names:
            node = self.classes.all[name]
            if (
                name != class_node.name
                and not _sets_true(node, "__abstract__")  # its columns are copied
                and (self.detect(node) or self._is_single_table(node))
            ):
                excluded.update(self.classes.mro(name) or self.classes.dfs_order(node, set()))
        return excluded

    def collect(self, class_node: ast.ClassDef) -> Tuple[Dict[str, FieldInfo], Dict[str, _Rel]]:
        """The class's own members; single-table subclasses are added in :meth:`finish`."""
        return self._collect_own(class_node)

    def _collect_own(
        self, class_node: ast.ClassDef
    ) -> Tuple[Dict[str, FieldInfo], Dict[str, _Rel]]:
        """The members a class stores in its own table, or adds to its parent's.

        A mixin attribute that a mapped ancestor already maps is left out when
        the ancestor's comes first, as SQLAlchemy's ``attribute_is_overridden``
        decides: walking the MRO, a mapped ancestor that maps the attribute
        wins, a mixin that assigns it a value (``= mapped_column()``) keeps
        it, and an annotation alone is passed over.
        """
        fields, rels = super().collect(class_node)
        mapped = self._mapped_ancestry(class_node, self.classes.dfs_order(class_node, set()))
        mapped_attrs = {name: self._mapped_attrs(name) for name in mapped}
        candidates = set().union(*mapped_attrs.values()) - set(self.declared_names(class_node))
        for attr in candidates:
            for ancestor in self._ancestors(class_node.name):
                if ancestor in mapped_attrs:
                    if attr in mapped_attrs[ancestor]:
                        fields.pop(attr, None)
                        rels.pop(attr, None)
                        break
                elif _assigns_value(self.classes.all[ancestor], attr):
                    break
        return fields, rels

    def _mapped_attrs(self, name: str) -> Set[str]:
        """Attributes class ``name`` maps itself: its body's, or its Core table's columns.

        A Core column is mapped under its key (``key=``, else its name).
        """
        mapped = self._mapped_tables.get(name)
        if mapped is not None:
            return {
                key
                for arg in mapped.table.args
                if isinstance(arg, ast.Call) and is_call_to(arg, "Column")
                for key in [explicit_column_name(arg)]
                if key is not None
            }
        return set(self.declared_names(self.classes.all[name]))

    def _add_single_table_columns(self, entity: EntityInfo, class_node: ast.ClassDef) -> None:
        """Add the columns of single-table subclasses to the entity's table (#302).

        Each subclass's columns get their own explicit names first, so a column
        is identified by its database name: one declared again
        (``use_existing_column=True``) keeps its first declaration
        (only the later annotation's nullability is applied). An explicit ``key=`` is recorded for
        :meth:`finalize`. Relationships belong to the subclass's mapper, which
        has no entity, so they are not drawn (#317).
        """
        subs = self._single_table_subclasses.get(class_node.name, [])
        if not subs:
            return
        columns = {f.name: f for f in entity.fields}
        for sub in subs:
            sub_node = self.classes.all[sub]
            keys = self._db_column_names(sub_node)
            names = self._db_column_names(sub_node, use_key=False)
            for attr, field in self._collect_own(sub_node)[0].items():
                field.name = names.get(attr, attr)
                key = keys.get(attr, attr)
                if key != field.name:
                    self._renamed_keys.setdefault(entity.table_name, {})[key] = field.name
                existing = columns.get(field.name)
                if existing is None:
                    columns[field.name] = field
                else:
                    # SQLAlchemy reuses the column and only applies the later
                    # annotation's nullability, not an explicit nullable=.
                    existing.is_nullable = self._annotation_nullable.get(
                        id(field), (field, field.is_nullable)
                    )[1]
        entity.fields = list(columns.values())

    def finish(self, entity: EntityInfo, class_node: ast.ClassDef) -> None:
        """A class mapped to a Core table has exactly that table's columns.

        Either way, the columns its single-table subclasses add follow.
        """
        mapped = self._mapped_tables.get(class_node.name)
        if mapped is None:
            super().finish(entity, class_node)
            self._add_single_table_columns(entity, class_node)
            return
        entity.fields = core_table_fields(mapped.table)
        self._note_core_table(entity, mapped.table)
        self._add_single_table_columns(entity, class_node)
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
        # SQLModel and SQLAlchemy keep separate metadata: a foreign key only
        # references a table of its own kind (a Core table on SQLModel.metadata
        # is SQLModel's).
        # Several MetaData collections of one kind may define the same table:
        # such a reference is ambiguous (None) and keeps no type.
        columns: Dict[str, Dict[str, FieldInfo | None]] = {}
        for entity in entities.values():
            kind = self._metadata_kind(entity)
            for f in entity.fields:
                ref = f"{entity.table_name}.{f.name}"
                known = columns.setdefault(kind, {})
                known[ref] = None if ref in known else f
        # A chain of ForeignKey-only columns takes the type from its end.
        changed = True
        while changed:
            changed = False
            for f, kind in self._untyped:
                target = columns.get(kind, {}).get(f.foreign_table or "")
                if not f.type_str and target is not None and target.type_str:
                    f.type_str = target.type_str
                    changed = True
        for name, properties in self._properties.items():
            mapped_entity = entities.get(name)
            if mapped_entity is not None:
                self._add_properties(mapped_entity, properties, entities)

    def _metadata_kind(self, entity: EntityInfo) -> str:
        """The metadata an entity's table is on: its source, or SQLModel's for a Core table."""
        return "sqlmodel" if self._sqlmodel_core.get(id(entity)) is entity else entity.source

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
            # An option set to None or an empty collection is SQLAlchemy's default.
            options = {kw.arg: kw.value for kw in value.keywords if kw.arg and not _unset(kw.value)}
            # A secondary= many-to-many is drawn through its association table.
            if "secondary" in options:
                continue
            target = _relationship_target(value)
            if target is None:
                continue
            uselist = options.get("uselist")
            target_entity = entities.get(target)
            if target == entity.name:
                # Self-referential: one-to-many unless remote_side= names the
                # referenced side; naming the foreign-key columns keeps it one-to-many.
                own = _references(entity, entity.table_name)
                remote = options.get("remote_side")
                names = _column_names(remote) if remote is not None else set()
                on_foreign_key = bool(names) and names <= {f.name for f in own}
                references: List[FieldInfo] = (
                    own if remote is not None and not on_foreign_key else []
                )
            elif target_entity is not None:
                references = _references(entity, target_entity.table_name)
            else:
                references = []
            explicit = uselist.value if isinstance(uselist, ast.Constant) else None
            if explicit is True:  # uselist=True: a collection whatever the direction
                kind, nullable = "many", False
            elif references:
                kind, nullable = "one", any(f.is_nullable for f in references)
            elif explicit is False:
                kind, nullable = "one", True
            else:
                kind, nullable = "many", False
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
            # ForeignKeyConstraint(["col"], ["t.name"], link_to_name=True): the
            # local column is named through its key, the target by its name.
            if is_call_to(arg, "ForeignKeyConstraint") and isinstance(arg, ast.Call):
                local = _strings_of(arg.args[0]) if arg.args else []
                field = columns.get(renamed_back(call, local[0])) if len(local) == 1 else None
                if field is not None and any(
                    kw.arg == "link_to_name"
                    and isinstance(kw.value, ast.Constant)
                    and kw.value.value is True
                    for kw in arg.keywords
                ):
                    self._name_targets[id(field)] = field
                continue
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
                self._untyped.append((field, self._metadata_kind(entity)))
        if renamed:
            owner._renamed_keys.setdefault(entity.table_name, {}).update(renamed)


def renamed_back(call: ast.Call, key: str) -> str:
    """The name of the column of a Core ``Table(...)`` whose key is ``key``."""
    for arg in call.args:
        if is_call_to(arg, "Column") and isinstance(arg, ast.Call):
            if explicit_column_name(arg) == key:
                return explicit_column_name(arg, use_key=False) or key
    return key


class _MappedTable(NamedTuple):
    """The Core table a class is mapped to."""

    table: ast.Call
    #: ``map_imperatively(..., properties={...})``, if given as a dict literal.
    properties: ast.Dict | None = None
    #: Mapped with ``map_imperatively()``: its subclasses' annotations map no columns.
    imperative: bool = False


def module_tables(tree: ast.Module) -> List[Tuple[str, ast.Call]]:
    """``(variable, call)`` for each module-level ``name = Table(...)``, in source order.

    An annotated assignment (``users: Table = Table(...)``) counts too.
    """
    found: List[Tuple[str, ast.Call]] = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            target, value = node.target, node.value
        else:
            continue
        if (
            isinstance(target, ast.Name)
            and isinstance(value, ast.Call)
            and is_call_to(value, "Table")
            and _has_metadata(value)
        ):
            found.append((target.id, value))
    return found


def _has_metadata(call: ast.Call) -> bool:
    """Whether a ``Table(...)`` call passes a metadata: SQLAlchemy requires one.

    Tells a Core table from another library's ``Table`` (``rich.table.Table("T",
    Column("Age"))``), whose second argument is no metadata.
    """
    if any(kw.arg == "metadata" for kw in call.keywords):
        return True
    return len(call.args) > 1 and not (
        isinstance(call.args[1], ast.Constant) or is_call_to(call.args[1], "Column")
    )


def mapped_tables(
    trees: Iterable[ast.Module],
    classes: Mapping[str, ast.ClassDef],
    tree_of: Callable[[ast.ClassDef], ast.Module | None],
) -> Dict[str, _MappedTable]:
    """Classes mapped to a Core table, by class name.

    ``class X(Base): __table__ = Table(...)`` (or a module-level table
    variable, #297), and ``registry.map_imperatively(X, table, properties=...)``
    anywhere in a scanned file, e.g. inside a ``start_mappers()`` function (#306).
    A table variable is looked up in the same file first, then in the one
    scanned file that defines it (not when several do).
    """
    trees = list(trees)
    per_tree = {id(tree): dict(module_tables(tree)) for tree in trees}
    # A variable defined in several files is ambiguous elsewhere: not resolved.
    everywhere: Dict[str, ast.Call | None] = {}
    for tree in trees:
        for name, call in per_tree[id(tree)].items():
            everywhere[name] = None if name in everywhere else call

    def resolve(value: ast.expr | None, tree: ast.Module | None) -> ast.Call | None:
        if isinstance(value, ast.Call) and is_call_to(value, "Table"):
            return value
        if isinstance(value, ast.Name):
            local = per_tree.get(id(tree), {}) if tree is not None else {}
            return local.get(value.id) or everywhere.get(value.id)
        if isinstance(value, ast.Attribute):  # tables.batches
            return everywhere.get(value.attr)
        return None

    def class_name(value: ast.expr | None) -> str | None:
        """The mapped class, also qualified (``model.Batch`` from a domain module)."""
        name = expr_name(value) if isinstance(value, (ast.Name, ast.Attribute)) else None
        name = name.rpartition(".")[2] if name is not None else None
        return name if name in classes else None

    found: Dict[str, _MappedTable] = {}
    for name, class_node in classes.items():
        for node in class_node.body:
            # __table__ = Table(...), also annotated (__table__: Table = ...).
            targets = (
                node.targets
                if isinstance(node, ast.Assign)
                else [node.target]
                if isinstance(node, ast.AnnAssign)
                else []
            )
            if any(isinstance(t, ast.Name) and t.id == "__table__" for t in targets):
                assert isinstance(node, (ast.Assign, ast.AnnAssign))
                table = resolve(node.value, tree_of(class_node))
                if table is not None:
                    found[name] = _MappedTable(table)
    for tree in trees:
        for mapping in ast.walk(tree):
            if not (
                isinstance(mapping, ast.Call)
                and isinstance(mapping.func, ast.Attribute)
                and mapping.func.attr == "map_imperatively"
            ):
                continue
            options = {kw.arg: kw.value for kw in mapping.keywords if kw.arg}
            args = list(mapping.args)
            mapped = class_name(args[0] if args else options.get("class_"))
            if mapped is None:
                continue
            table = resolve(args[1] if len(args) > 1 else options.get("local_table"), tree)
            if table is None:
                continue  # e.g. single-table inheritance: no table of its own
            properties = options.get("properties")
            found[mapped] = _MappedTable(
                table, properties if isinstance(properties, ast.Dict) else None, imperative=True
            )
    return found


def _column_names(value: ast.expr) -> set[str]:
    """Column names a ``remote_side=`` names: ``[t.c.id]``, ``"Node.id"``, ``[id]``."""
    if isinstance(value, ast.Lambda):
        value = value.body
    items = value.elts if isinstance(value, (ast.List, ast.Tuple, ast.Set)) else [value]
    names: set[str] = set()
    for item in items:
        if isinstance(item, ast.Constant) and isinstance(item.value, str):
            names.add(item.value.rpartition(".")[2])
        elif isinstance(item, ast.Attribute):
            names.add(item.attr)
        elif isinstance(item, ast.Name):
            names.add(item.id)
    return names


def _unset(value: ast.expr) -> bool:
    """``None`` or an empty list / tuple: an option left at its default."""
    if isinstance(value, ast.Constant):
        return value.value is None
    return isinstance(value, (ast.List, ast.Tuple)) and not value.elts


def _references(entity: EntityInfo, table: str) -> List[FieldInfo]:
    """The foreign-key columns of ``entity`` that reference ``table``."""
    return [
        f
        for f in entity.fields
        # "schema.table.column": schema= is not read, the table name is matched.
        if f.is_foreign_key
        and (f.foreign_table or "").rpartition(".")[0].rpartition(".")[2] == table
    ]


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
        name = expr_name(target)  # model.Customer -> Customer
        return name.rpartition(".")[2] if name is not None else None
    return None


def has_tablename(class_node: ast.ClassDef) -> bool:
    """Check if a class assigns __tablename__ (annotated or plain).

    ``__tablename__ = None`` declares no table: a subclass of a mapped class
    that sets it is stored in its parent's table (single-table inheritance).
    """
    for node in class_node.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "__tablename__":
                return not _is_none(node.value)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__tablename__":
                    return not _is_none(node.value)
    return False


def _is_none(value: ast.expr | None) -> bool:
    return isinstance(value, ast.Constant) and value.value is None


def _defines_function(class_node: ast.ClassDef, name: str) -> bool:
    """Whether the class body defines a method ``name`` (e.g. a ``@declared_attr``)."""
    return any(
        isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name
        for item in class_node.body
    )


def declared_attr_member(node: ast.FunctionDef | ast.AsyncFunctionDef) -> ast.AnnAssign | None:
    """A ``@declared_attr`` method as the annotated attribute it maps, or None (#298).

    ``@declared_attr def owner(cls) -> Mapped["Owner"]: return relationship()``
    becomes ``owner: Mapped["Owner"] = relationship()``. Only a method with a
    return annotation whose body is a single ``return`` (after a docstring) is
    read; ``@declared_attr.directive`` (``__tablename__``, ``__table_args__``)
    maps no attribute.
    """
    if not any(_is_declared_attr(decorator) for decorator in node.decorator_list):
        return None
    if node.returns is None or node.name.startswith("_"):
        return None
    body = node.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    if len(body) != 1 or not isinstance(body[0], ast.Return) or body[0].value is None:
        return None
    member = ast.AnnAssign(
        target=ast.Name(id=node.name, ctx=ast.Store()),
        annotation=node.returns,
        value=body[0].value,
        simple=1,
    )
    return ast.copy_location(member, node)


def _is_declared_attr(decorator: ast.expr) -> bool:
    """``@declared_attr`` (also qualified) or ``@declared_attr.cascading``."""
    if isinstance(decorator, ast.Attribute) and decorator.attr == "cascading":
        decorator = decorator.value
    return expr_name(decorator) == "declared_attr"


def _assigns_value(class_node: ast.ClassDef, name: str) -> bool:
    """Whether the class body assigns ``name`` a value, not just an annotation.

    A ``@declared_attr`` method returning the attribute counts (#298).
    """
    for node in class_node.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == name and declared_attr_member(node) is not None:
                return True
            continue
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        else:
            continue
        if any(isinstance(t, ast.Name) and t.id == name for t in targets):
            return True
    return False


def _assigns(class_node: ast.ClassDef, name: str) -> bool:
    """Whether the class body assigns ``name`` (annotated or plain)."""
    for node in class_node.body:
        targets = (
            node.targets
            if isinstance(node, ast.Assign)
            else [node.target]
            if isinstance(node, ast.AnnAssign)
            else []
        )
        if any(isinstance(t, ast.Name) and t.id == name for t in targets):
            return True
    return False


def _sets_true(class_node: ast.ClassDef, name: str) -> bool:
    """Whether the class body sets ``name = True`` (annotated or plain)."""
    for node in class_node.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        if any(isinstance(t, ast.Name) and t.id == name for t in targets):
            if isinstance(node.value, ast.Constant) and node.value.value is True:
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
                by_name[explicit_column_name(arg) or field.name] = field
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
    col_name = explicit_column_name(call, use_key=False)
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
    # An Identity() column is NOT NULL unless it says otherwise.
    identity = any(is_call_to(arg, "Identity") for arg in call.args)
    fk_target = extract_foreign_key_arg(call)

    # The column type: type_=, else the first positional argument (after the
    # name) that is not a schema item such as ForeignKey(...).
    positional = (
        call.args[1:] if call.args and isinstance(call.args[0], ast.Constant) else list(call.args)
    )
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
        is_nullable=(
            not (is_primary_key or identity)
            if nullable is None
            else nullable and not is_primary_key
        ),
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
        first = call.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            return "str"  # Enum("open", "closed", name="status")
        enum_class = expr_name(first)
        if enum_class is not None:
            return enum_class.rpartition(".")[2]
    options = {
        kw.arg: kw.value.value
        for kw in (call.keywords if call is not None else [])
        if kw.arg and isinstance(kw.value, ast.Constant)
    }
    # Options that change the Python type: Uuid(as_uuid=False) holds strings,
    # Numeric(asdecimal=False) floats and Float(asdecimal=True) Decimals.
    if name in ("Uuid", "UUID") and options.get("as_uuid") is False:
        return "str"
    if "asdecimal" in options and name in _DECIMAL_TYPES:
        return "Decimal" if options["asdecimal"] else "float"
    return _PYTHON_TYPES.get(name, name)


#: Types whose ``asdecimal=`` option picks ``Decimal`` or ``float``.
_DECIMAL_TYPES = frozenset(
    {
        "Numeric",
        "NUMERIC",
        "DECIMAL",
        "Float",
        "Double",
        "REAL",
        "FLOAT",
        "DOUBLE",
        "DOUBLE_PRECISION",
    }
)

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
