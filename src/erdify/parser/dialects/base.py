"""The interface every model framework ("dialect") implements, and its context."""

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, ClassVar, Dict, Iterable, List, Mapping, Set, Tuple

from ...config import EntityInfo, FieldInfo
from ..annotations import is_call_to
from ..common import _ClassMembers, _Rel, to_snake_case
from ..inheritance import ClassIndex, merge_members, reorder


@dataclass
class ParseContext:
    """What a dialect may read besides the class it is parsing.

    Attributes:
        classes: Every class definition in the scanned files.
        infer_keys: Infer keys for keyless sources (``--infer-keys``).
        django_raw_types: Keep Django field names (``--django-raw-types``).
        base_classes: Extra base-class names treated as Pydantic models.
        dialects: One instance of every dialect, in ``MODEL_SOURCES`` order;
            created on first use.
        aliases_for: Column type aliases visible where a class is defined
            (``intpk = Annotated[int, mapped_column(primary_key=True)]``,
            #241, #249, #250).
        file_of: The file a class is defined in, or None if unknown.
        trees: The syntax trees of every scanned file.
        tree_of: The syntax tree of the file a class is defined in, or None.
    """

    classes: ClassIndex = field(default_factory=lambda: ClassIndex({}))
    infer_keys: bool = False
    django_raw_types: bool = False
    base_classes: Set[str] = field(default_factory=set)
    dialects: List["Dialect"] = field(default_factory=list)
    aliases_for: Callable[[ast.ClassDef], Mapping[str, ast.expr]] = lambda _class_node: {}
    file_of: Callable[[ast.ClassDef], Path | None] = lambda _class_node: None
    trees: List[ast.Module] = field(default_factory=list)
    tree_of: Callable[[ast.ClassDef], ast.Module | None] = lambda _class_node: None

    def all_dialects(self) -> List["Dialect"]:
        """Every dialect, in classification order, bound to this context."""
        if not self.dialects:
            from . import DIALECTS  # the registry imports this module

            self.dialects = [dialect(self) for dialect in DIALECTS]
        return self.dialects

    def dialect(self, kind: str) -> "Dialect":
        """The dialect producing model kind ``kind``."""
        return next(d for d in self.all_dialects() if d.kind == kind)

    def classify(self, class_node: ast.ClassDef) -> str | None:
        """The model kind of a class, or None if it is not a drawable entity.

        Dialects are tried in ``MODEL_SOURCES`` order; one that detects the
        class but finds it not drawable (a Django abstract base) ends the
        search. ``--sources`` is not applied here.
        """
        for dialect in self.all_dialects():
            if dialect.detect(class_node):
                return dialect.kind if dialect.is_drawable(class_node) else None
        return None


class Dialect:
    """How one model framework is detected and how its class bodies are read.

    The dialect of an entity is chosen from the concrete class, and the same
    dialect reads every ancestor of it (a mixin is read the way the model that
    inherits it is). Merging the ancestors follows the MRO and is shared
    (:mod:`..inheritance`); a dialect only adjusts it through the hooks below.
    One instance lives for one parse run, so per-run caches belong on it.

    Args:
        ctx: The shared parse context.
    """

    #: The model kind this dialect produces (one of ``MODEL_SOURCES``).
    kind: ClassVar[str]
    #: Describes objects rather than tables: ``--infer-keys`` applies, a field
    #: typed as another model is a relationship, and an optional primary key
    #: really is optional.
    keyless: ClassVar[bool] = False
    #: Reads SQLAlchemy column settings from ``Annotated`` metadata and column
    #: type aliases (#241); only SQLAlchemy itself does.
    reads_annotated_columns: ClassVar[bool] = False
    #: Whether ``x: T = <plain value>`` declares a column with that default.
    #: SQLAlchemy maps no column for it (#294).
    plain_value_is_column: ClassVar[bool] = True

    def __init__(self, ctx: ParseContext):
        self.ctx = ctx
        self.classes = ctx.classes

    # -- detection --------------------------------------------------------

    @classmethod
    def builtin_classes(
        cls, trees: Iterable[ast.Module], defined: Set[str]
    ) -> Dict[str, ast.ClassDef]:
        """Framework classes to add to the scanned ones, by name.

        For base classes that ship with the framework and that models build
        on (Django's ``AbstractUser``), so their members are inherited even
        though their source isn't scanned. ``defined`` holds the names the
        scanned files define; those are never replaced. None by default.
        """
        return {}

    def detect(self, class_node: ast.ClassDef) -> bool:
        """Whether the class belongs to this framework."""
        raise NotImplementedError

    def is_drawable(self, class_node: ast.ClassDef) -> bool:
        """Whether a detected class becomes an entity (not, e.g., an abstract base).

        A detected class that is not drawable belongs to no other framework either.
        """
        return True

    def skip_reason(self, class_node: ast.ClassDef) -> str | None:
        """A warning to print instead of drawing a detected class, or None to draw it."""
        return None

    def extra_entities(self, trees: Iterable[ast.Module]) -> List[EntityInfo]:
        """Entities that are not classes (e.g. SQLAlchemy Core tables). None by default."""
        return []

    # -- reading a class body -------------------------------------------------

    def table_name(self, class_node: ast.ClassDef) -> str | None:
        """The table name the class declares, if any; ``__tablename__`` by default."""
        table_name = None
        for node in class_node.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.target.id == "__tablename__" and isinstance(node.value, ast.Constant):
                    table_name = str(node.value.value)
            elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "__tablename__":
                        table_name = str(node.value.value)
        return table_name

    def default_table_name(self, class_node: ast.ClassDef) -> str:
        """The table name of a class that declares none; the snake_case class name."""
        return to_snake_case(class_node.name)

    def class_fields(
        self, class_node: ast.ClassDef, concrete: str
    ) -> Tuple[Dict[str, FieldInfo], Dict[str, _Rel]]:
        """The fields and relationships a single class body declares.

        ``concrete`` is the model a ``"self"`` reference in this body points at.
        """
        raise NotImplementedError

    def declared_names(self, class_node: ast.ClassDef) -> List[str]:
        """Attribute names a class body declares, shadowing inherited ones.

        Every annotated attribute shadows an inherited one, also when it yields
        neither a field nor a relationship (e.g. a relationship() whose
        annotation names no single class, or link_model=).
        """
        return [
            node.target.id
            for node in class_node.body
            if isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and not node.target.id.startswith("_")
        ]

    def class_members(self, class_node: ast.ClassDef, concrete: str) -> _ClassMembers:
        """A single class body's fields, relationships, and declared attribute names."""
        fields, rels = self.class_fields(class_node, concrete)
        return fields, rels, self.declared_names(class_node)

    # -- merging the hierarchy ------------------------------------------------

    def self_owner(self, name: str, merge_order: List[str]) -> str:
        """The model a ``"self"`` reference declared in class ``name`` points at."""
        return name

    def table_classes(self, class_node: ast.ClassDef, names: List[str]) -> Set[str]:
        """Which of ``names`` (the class and its ancestors) store columns in its table.

        All of them by default: a base's members are copied into the model.
        Django's multi-table inheritance and SQLAlchemy's mapped-class
        inheritance keep a concrete parent's in its own table.
        """
        return set(names)

    def drop_on_merge(
        self,
        fields: Dict[str, FieldInfo],
        rels: Dict[str, _Rel],
        attr: str,
        class_fields: Dict[str, FieldInfo],
        class_rels: Dict[str, _Rel],
    ) -> None:
        """Drop what earlier classes stored for a redeclared ``attr``.

        Same key and kind is left to the merge's ``update()``, which replaces
        it in place; a column redeclared as a relationship (or vice versa), or
        an attribute that now yields nothing, drops the inherited entry.
        """
        if attr in class_fields:
            rels.pop(attr, None)
        elif attr in class_rels:
            fields.pop(attr, None)
        else:
            fields.pop(attr, None)
            rels.pop(attr, None)

    def drop_on_listing(
        self, fields: Dict[str, FieldInfo], rels: Dict[str, _Rel], attr: str
    ) -> None:
        """Whether a body's redeclaration moves an inherited attribute; not by default."""

    def merge(
        self,
        class_node: ast.ClassDef,
        merge_order: List[str],
        members: Dict[str, _ClassMembers],
    ) -> Tuple[Dict[str, FieldInfo], Dict[str, _Rel]]:
        """Merge the members of the class and its ancestors; later classes win."""
        return merge_members(merge_order, members, self)

    def collect(self, class_node: ast.ClassDef) -> Tuple[Dict[str, FieldInfo], Dict[str, _Rel]]:
        """Collect the fields and relationships of a class and all its ancestors.

        Which declaration of an attribute wins follows the MRO
        (:meth:`ClassIndex.merge_order`), or a dialect's own :meth:`merge`. The
        order they are listed in is the one the pre-MRO merge produced
        (:meth:`ClassIndex.listing_order`), so resolving by MRO does not
        reorder the output.
        """
        dfs_order = self.classes.dfs_order(class_node, set())
        merge_order = self.classes.merge_order(class_node)
        own = self.table_classes(class_node, dfs_order)
        empty: _ClassMembers = ({}, {}, [])
        members = {
            name: (
                self.class_members(self.classes.all[name], self.self_owner(name, merge_order))
                if name in own
                else empty
            )
            for name in dfs_order
        }
        order_fields, order_rels = self.classes.listing_order(class_node, set(), members, self)
        fields, rels = self.merge(class_node, merge_order, members)
        return reorder(fields, order_fields), reorder(rels, order_rels)

    # -- finishing the entity -------------------------------------------------

    def finalize(self, entities: Mapping[str, EntityInfo]) -> None:
        """Adjust the dialect's entities once all entities are built. Nothing by default.

        For changes that cross entities, e.g. renaming a column that other
        entities' foreign keys reference.
        """

    def finish(self, entity: EntityInfo, class_node: ast.ClassDef) -> None:
        """Adjust the built entity: mark columns made unique by ``__table_args__``."""
        # Single-column UniqueConstraint / unique Index in __table_args__ (#218).
        # Constraints name the *database* column, which mapped_column("col", ...)
        # may set apart from the attribute name (#221).
        # A string names the DB column; a bare reference names the attribute.
        unique_cols, unique_refs = self._table_args_unique_columns(class_node)
        db_names = self._db_column_names(class_node)
        for f in entity.fields:
            if f.is_primary_key:
                continue
            if db_names.get(f.name, f.name) in unique_cols or f.name in unique_refs:
                f.is_unique = True

    def _db_column_names(self, class_node: ast.ClassDef, use_key: bool = True) -> Dict[str, str]:
        """Map attribute name -> explicit DB column name for a class and its bases.

        See :meth:`_explicit_column_name` for the recognized forms and
        ``use_key``. A column without an explicit name maps to itself, so a
        redeclaration without one overrides an inherited name. Bases resolve in
        the same order as the fields (:meth:`ClassIndex.merge_order`), so the
        name matches the winning column.
        """
        names: Dict[str, str] = {}
        for class_name in self.classes.merge_order(class_node):
            for node in self.classes.all[class_name].body:
                if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    db_name = self._explicit_column_name(node.value, use_key)
                    names[node.target.id] = db_name if db_name is not None else node.target.id
        return names

    @classmethod
    def _explicit_column_name(cls, value: ast.expr | None, use_key: bool = True) -> str | None:
        """Return the explicit name of this column, if any.

        Recognizes ``mapped_column("name", ...)`` / ``mapped_column(name="name")``,
        and SQLModel's ``Field(sa_column=Column("name", ...))`` /
        ``Field(sa_column_kwargs={"name": "name"})``. With ``use_key``, it is the
        name a string constraint uses: SQLAlchemy resolves a constraint's string
        column through the column *key*, which defaults to the name, so an
        explicit ``key=`` takes precedence. Without it, it is the database
        column's name.
        """
        if value is None:
            return None
        if is_call_to(value, "mapped_column") or is_call_to(value, "Column"):
            for kw in value.keywords:
                if (
                    use_key
                    and kw.arg == "key"
                    and isinstance(kw.value, ast.Constant)
                    and isinstance(kw.value.value, str)
                ):
                    return kw.value.value
            if (
                value.args
                and isinstance(value.args[0], ast.Constant)
                and isinstance(value.args[0].value, str)
            ):
                return value.args[0].value
            for kw in value.keywords:
                if (
                    kw.arg == "name"
                    and isinstance(kw.value, ast.Constant)
                    and isinstance(kw.value.value, str)
                ):
                    return kw.value.value
            return None
        if is_call_to(value, "Field"):
            for kw in value.keywords:
                if kw.arg == "sa_column":
                    return cls._explicit_column_name(kw.value, use_key)
                if kw.arg == "sa_column_kwargs" and isinstance(kw.value, ast.Dict):
                    opts = {
                        key.value: val.value
                        for key, val in zip(kw.value.keys, kw.value.values)
                        if isinstance(key, ast.Constant)
                        and isinstance(val, ast.Constant)
                        and isinstance(val.value, str)
                    }
                    # As above: an explicit key wins over the name.
                    found = opts.get("key", opts.get("name")) if use_key else opts.get("name")
                    if isinstance(found, str):
                        return found
        return None

    @classmethod
    def _table_args_unique_columns(cls, class_node: ast.ClassDef) -> Tuple[set[str], set[str]]:
        """Columns made unique on their own by the class's ``__table_args__``.

        Recognizes ``UniqueConstraint("col")`` and ``Index("name", "col",
        unique=True)`` with exactly one column, in a tuple/list ``__table_args__``
        (a trailing options dict is ignored). Composite constraints and partial
        indexes (``*_where=``) do not make a column unique and are skipped.

        Returns ``(db_columns, attribute_refs)``: a string names the *database*
        column, while a bare reference (``UniqueConstraint(account_id)``) names
        the attribute declared earlier in the class body.
        """
        value: ast.expr | None = None
        for node in class_node.body:
            if isinstance(node, ast.Assign):
                if any(isinstance(t, ast.Name) and t.id == "__table_args__" for t in node.targets):
                    value = node.value
            elif (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id == "__table_args__"
            ):
                value = node.value
        if not isinstance(value, (ast.Tuple, ast.List)):
            return set(), set()
        return single_column_uniques(value.elts)


def explicit_column_name(value: ast.expr | None, use_key: bool = True) -> str | None:
    """The explicit name (or, with ``use_key``, key) of a column declaration, if any.

    See :meth:`Dialect._explicit_column_name`; also reads a Core ``Column(...)``.
    """
    return Dialect._explicit_column_name(value, use_key)


def single_column_uniques(items: Iterable[ast.expr]) -> Tuple[Set[str], Set[str]]:
    """Columns made unique on their own by ``UniqueConstraint`` / unique ``Index`` items.

    The items of a ``__table_args__`` tuple or the arguments of a Core
    ``Table(...)``. Only constraints and indexes over exactly one column
    count; a partial index (``*_where=``) does not make a column unique.

    Returns ``(db_columns, attribute_refs)``: a string names the database
    column, a bare name an attribute declared earlier in the class body.
    """
    columns: Set[str] = set()
    refs: Set[str] = set()
    for item in items:
        if is_call_to(item, "UniqueConstraint"):
            cols = item.args
        elif is_call_to(item, "Index"):
            if not any(
                kw.arg == "unique" and isinstance(kw.value, ast.Constant) and kw.value.value
                for kw in item.keywords
            ):
                continue
            # A partial index (postgresql_where=, sqlite_where=, ...) is only
            # unique over a subset of rows, so it does not imply a 1:1. A
            # literal `*_where=None` is "no predicate", i.e. not partial.
            if any(
                kw.arg
                and kw.arg.endswith("_where")
                and not (isinstance(kw.value, ast.Constant) and kw.value.value is None)
                for kw in item.keywords
            ):
                continue
            cols = item.args[1:]  # first positional arg is the index name
        else:
            continue
        if len(cols) == 1:
            col = cols[0]
            if isinstance(col, ast.Constant) and isinstance(col.value, str):
                columns.add(col.value)
            elif isinstance(col, ast.Name):
                refs.add(col.id)
    return columns, refs
