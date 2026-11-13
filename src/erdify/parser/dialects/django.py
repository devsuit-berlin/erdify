"""Django ORM: ``models.Model`` subclasses with ``*Field`` class attributes."""

import ast
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Set, Tuple

from ...config import EntityInfo, FieldInfo
from ..annotations import expr_name
from ..common import _ClassMembers, _Rel, is_enum_class
from .base import Dialect, ParseContext
from .django_apps import app_label, app_package
from .django_contrib import (
    CONTRIB_TABLES,
    DEFAULT_USER_MODEL,
    abstract_user_bases,
    contrib_bindings,
    contrib_target,
    imported_contrib_names,
)

#: Django relationship field constructs (everything else ending in "Field" is a column).
DJANGO_RELATIONSHIP_FIELDS = frozenset({"ForeignKey", "OneToOneField", "ManyToManyField"})

#: Django 5.2's composite primary key: a model field that makes no column (#276).
COMPOSITE_PRIMARY_KEY = "CompositePrimaryKey"

#: Bases that never make a class a Django model (plain mixins may use them).
_NON_MODEL_BASES = frozenset({"object", "Generic", "Protocol", "ABC"})

#: (field type, call, declaring class) of a model field.
_Declaration = Tuple[str, ast.Call, str]

#: Conservative Django field -> Python type map for readable, source-consistent
#: output. Ambiguous/lossy fields (JSONField, FileField, ImageField, custom or
#: third-party fields) are intentionally omitted so they fall back to the Django
#: field name rather than fake a concrete type. Use --django-raw-types to keep the
#: original Django field names instead.
DJANGO_FIELD_TYPE_MAP = {
    "CharField": "str",
    "TextField": "str",
    "SlugField": "str",
    "EmailField": "str",
    "URLField": "str",
    "GenericIPAddressField": "str",
    "FilePathField": "str",
    "IntegerField": "int",
    "BigIntegerField": "int",
    "SmallIntegerField": "int",
    "PositiveIntegerField": "int",
    "PositiveSmallIntegerField": "int",
    "PositiveBigIntegerField": "int",
    "AutoField": "int",
    "BigAutoField": "int",
    "SmallAutoField": "int",
    "FloatField": "float",
    "DecimalField": "Decimal",
    "BooleanField": "bool",
    "DateTimeField": "datetime",
    "DateField": "date",
    "TimeField": "time",
    "DurationField": "timedelta",
    "UUIDField": "UUID",
    "BinaryField": "bytes",
}


class DjangoDialect(Dialect):
    """A subclass of Django's ``models.Model``, directly or via ancestors.

    An abstract base (``class Meta: abstract = True``) is inherited but not
    drawn itself, and is not claimed by any other framework; neither is a proxy
    model (``proxy = True``), which has no table of its own.

    A model subclassing a *concrete* model (multi-table inheritance, #233) gets
    its own table: its own fields, those of its abstract bases, and a
    ``<parent>_ptr`` one-to-one link to each direct concrete parent. The first
    link is the primary key unless the model declares one.
    """

    kind = "django"

    def __init__(self, ctx: ParseContext):
        super().__init__(ctx)
        self._target_column_cache: Dict[Tuple[str, str | None], Tuple[str, str]] = {}
        self._parents_cache: Dict[str, List[str]] = {}
        self._base_parents_cache: Dict[str, List[str]] = {}
        self._lower_names: Dict[str, str] | None = None
        self._links_cache: Dict[str, List[Tuple[str, str]]] = {}
        self._app_labels: Dict[Path, str] = {}
        # id(FieldInfo) of each foreign-key column -> the model it references, so
        # db_column renames follow the model, not just its table (#275).
        self._fk_targets: Dict[int, str] = {}
        self._user_model_name: str | None = None
        self._declaring: Dict[int, ast.ClassDef] | None = None
        self._bindings: Dict[Tuple[int, int], Dict[str, str]] = {}
        self._declarations: Dict[str, Dict[str, _Declaration]] = {}

    @classmethod
    def builtin_classes(
        cls, trees: Iterable[ast.Module], defined: Set[str]
    ) -> Dict[str, ast.ClassDef]:
        """Django's abstract user bases, when a scanned file imports them (#277)."""
        return abstract_user_bases(imported_contrib_names(trees), defined)

    def detect(self, class_node: ast.ClassDef) -> bool:
        return self._inherits_django_model(class_node)

    def is_drawable(self, class_node: ast.ClassDef) -> bool:
        return not (self._meta_flag(class_node, "abstract") or self._meta_flag(class_node, "proxy"))

    def table_name(self, class_node: ast.ClassDef) -> str | None:
        """``__tablename__`` if set, else ``Meta.db_table``, also an inherited one (#279)."""
        table_name = super().table_name(class_node)
        if not table_name:
            db_table = self._meta_constant(class_node, "db_table")
            if isinstance(db_table, str):
                table_name = db_table
        return table_name

    def finalize(self, entities: Mapping[str, EntityInfo]) -> None:
        """Rename columns to their literal ``db_column`` (#275).

        Fields are keyed by attribute name while entities are built (``author``
        / ``author_id``), which inheritance, overrides and ``to_field`` lookups
        rely on. Only now are the columns renamed, and every foreign key that
        references a renamed column is pointed at the new name.
        """
        # Rename each entity's own columns where the entity is in hand.
        by_model: Dict[str, Dict[str, str]] = {}
        for name, entity in entities.items():
            node = self.classes.all.get(name)
            if entity.source != self.kind or node is None:
                continue
            columns = self._db_columns(node)
            if not columns:
                continue
            by_model[name] = columns
            for f in entity.fields:
                f.name = columns.get(f.name, f.name)
        # Point foreign keys at renamed columns, by the model they reference
        # (recorded when the FK column is built): unmanaged models may share a
        # table (Meta.db_table) and rename the same attribute differently.
        for entity in entities.values():
            if entity.source != self.kind:
                continue
            for f in entity.fields:
                if f.foreign_table is None:
                    continue
                table, _, column = f.foreign_table.rpartition(".")
                columns = by_model.get(self._fk_targets.get(id(f), ""), {})
                if column in columns:
                    f.foreign_table = f"{table}.{columns[column]}"

    def _db_columns(self, class_node: ast.ClassDef) -> Dict[str, str]:
        """Internal column name -> literal ``db_column`` for a model's own columns.

        The internal name is the attribute (``isbn``), or ``<attr>_id`` for a
        ``ForeignKey`` / ``OneToOneField``. Declarations resolve exactly like the
        fields (:meth:`_own_declarations`: overrides, ``name = None`` removals,
        a concrete parent's fields staying in the parent's table).
        """
        columns: Dict[str, str] = {}
        for attr, (field_type, call, _owner) in self._own_declarations(class_node).items():
            db_column = next((k.value for k in call.keywords if k.arg == "db_column"), None)
            # db_column="" is unset in Django: the default name applies.
            if not (
                isinstance(db_column, ast.Constant)
                and isinstance(db_column.value, str)
                and db_column.value
            ):
                continue
            if field_type in ("ForeignKey", "OneToOneField"):
                columns[f"{attr}_id"] = db_column.value
            elif field_type != "ManyToManyField":
                columns[attr] = db_column.value
        return columns

    def default_table_name(self, class_node: ast.ClassDef) -> str:
        """Django's default ``<app_label>_<model name>`` (#271).

        The model name is the class name lower-cased, not snake_case
        (``OrderItem`` -> ``orderitem``). Without a known app label (a class
        whose file is unknown) only the model name is returned.
        """
        label = self._app_label(class_node)
        model_name = class_node.name.lower()
        return f"{label}_{model_name}" if label else model_name

    def _app_label(self, class_node: ast.ClassDef) -> str | None:
        """``Meta.app_label`` (also inherited, #279), else the label of the model's app."""
        label = self._meta_constant(class_node, "app_label")
        if isinstance(label, str) and label:
            return label
        model_file = self.ctx.file_of(class_node)
        if model_file is None:
            return None
        package = app_package(model_file)
        if package not in self._app_labels:
            self._app_labels[package] = app_label(package)
        return self._app_labels[package]

    def class_fields(
        self, class_node: ast.ClassDef, concrete: str
    ) -> Tuple[Dict[str, FieldInfo], Dict[str, _Rel]]:
        return self._extract_django_fields(class_node, concrete)

    def declared_names(self, class_node: ast.ClassDef) -> List[str]:
        return self._django_declared_names(class_node)

    def self_owner(self, name: str, merge_order: List[str]) -> str:
        return self._django_self_owner(name, merge_order)

    def table_classes(self, class_node: ast.ClassDef, names: List[str]) -> Set[str]:
        """Leave out each concrete parent and its ancestors: they have their own table."""
        excluded: Set[str] = set()
        for parent in self._concrete_parents(class_node):
            parent_node = self.classes.all[parent]
            excluded.update(self.classes.mro(parent) or self.classes.dfs_order(parent_node, set()))
        return {name for name in names if name not in excluded}

    def merge(
        self,
        class_node: ast.ClassDef,
        merge_order: List[str],
        members: Dict[str, _ClassMembers],
    ) -> Tuple[Dict[str, FieldInfo], Dict[str, _Rel]]:
        """Take each field from the class whose declaration Django keeps.

        Which one that is follows Django, not Python attribute lookup
        (:meth:`_own_declarations`, #272, #280).
        """
        fields: Dict[str, FieldInfo] = {}
        rels: Dict[str, _Rel] = {}
        for attr, (field_type, _call, owner) in self._own_declarations(class_node).items():
            owner_fields, owner_rels, _ = members.get(owner, ({}, {}, []))
            if field_type in ("ForeignKey", "OneToOneField"):
                key = f"{attr}_id"
                if key in owner_fields:
                    fields[key] = owner_fields[key]
            elif field_type == "ManyToManyField":
                if attr in owner_rels:
                    rels[attr] = owner_rels[attr]
            elif attr in owner_fields:
                fields[attr] = owner_fields[attr]
        return fields, rels

    def drop_on_listing(
        self, fields: Dict[str, FieldInfo], rels: Dict[str, _Rel], attr: str
    ) -> None:
        """A Django body's redeclaration moves the attribute to the body's position.

        A Django attribute is stored under a key that depends on its kind
        (relationship ``owner`` vs. FK column ``owner_id``, #224), so all of
        them go.
        """
        rels.pop(attr, None)
        fields.pop(attr, None)
        inherited_fk = fields.get(f"{attr}_id")
        if inherited_fk is not None and inherited_fk.is_foreign_key:
            del fields[f"{attr}_id"]

    def unique_columns(self, class_node: ast.ClassDef) -> Tuple[Set[str], Set[str]]:
        """Columns ``Meta`` makes unique on their own; Django ignores ``__table_args__`` (#274).

        A single-field, unconditional ``UniqueConstraint(fields=[...])`` in
        ``Meta.constraints``, or a one-field ``Meta.unique_together`` entry.
        Composite, conditional (``condition=``) and expression constraints
        don't make one column unique. ``Meta`` may be inherited (#279).
        """
        declared = self._own_declarations(class_node)
        columns: Set[str] = set()
        for group in self._meta_unique_groups(class_node):
            if len(group) != 1:
                continue
            name = group[0]
            # A field name or an attname (`owner_id`), as Meta.get_field() accepts.
            if declared.get(name, ("",))[0] in ("ForeignKey", "OneToOneField"):
                name = f"{name}_id"
            columns.add(name)
        return set(), columns

    def _meta_unique_groups(self, class_node: ast.ClassDef) -> List[Tuple[str, ...]]:
        """The field-name groups of ``Meta.constraints`` / ``Meta.unique_together``.

        Only literal names count; a conditional or expression constraint, or
        one whose fields aren't literal, is left out.
        """
        groups: List[Tuple[str, ...]] = []
        constraints = self._meta_option(class_node, "constraints")
        if isinstance(constraints, (ast.List, ast.Tuple)):
            for item in constraints.elts:
                if not (isinstance(item, ast.Call) and expr_name(item.func) == "UniqueConstraint"):
                    continue
                if item.args or any(
                    kw.arg == "condition"
                    and not (isinstance(kw.value, ast.Constant) and kw.value.value is None)
                    for kw in item.keywords
                ):
                    continue  # expressions / a partial constraint
                names = next(
                    (_literal_names(kw.value) for kw in item.keywords if kw.arg == "fields"), None
                )
                if names:
                    groups.append(names)
        together = self._meta_option(class_node, "unique_together")
        if isinstance(together, (ast.List, ast.Tuple)) and together.elts:
            # Django's normalize_together(): a flat ("a", "b") is one group.
            flat = _literal_names(together)
            if flat is not None:
                groups.append(flat)
            else:
                for item in together.elts:
                    names = _literal_names(item)
                    if names:
                        groups.append(names)
        return groups

    def finish(self, entity: EntityInfo, class_node: ast.ClassDef) -> None:
        """Add the composite key, parent links and Django's implicit ``id`` primary key."""
        self._mark_composite_primary_key(entity, class_node)
        super().finish(entity, class_node)
        self._add_parent_links(entity, class_node)
        # Django implicitly adds an `id` primary key (BigAutoField since Django 3.2)
        # when no field declares primary_key=True and there is no parent link,
        # nor a composite key (even one whose fields erdify can't read).
        if not any(f.is_primary_key for f in entity.fields) and (
            self._composite_primary_key(class_node) is None
        ):
            entity.fields.insert(
                0,
                FieldInfo(
                    name="id",
                    type_str=self._django_display_type("BigAutoField"),
                    is_primary_key=True,
                ),
            )

    def _composite_primary_key(self, class_node: ast.ClassDef) -> List[str] | None:
        """The column keys of a ``CompositePrimaryKey`` the model has, if any (#276).

        Its arguments name fields or attnames (``order`` / ``order_id``); a
        ``ForeignKey`` is the ``<name>_id`` column. Non-literal arguments are
        left out, so the list may be empty.
        """
        declared = self._own_declarations(class_node)
        call = next(
            (c for t, c, _ in reversed(declared.values()) if t == COMPOSITE_PRIMARY_KEY), None
        )
        if call is None:
            return None
        keys: List[str] = []
        for arg in call.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                name = arg.value
                if declared.get(name, ("",))[0] in ("ForeignKey", "OneToOneField"):
                    name = f"{name}_id"
                keys.append(name)
        return keys

    def _mark_composite_primary_key(self, entity: EntityInfo, class_node: ast.ClassDef) -> None:
        """Make the columns of a ``CompositePrimaryKey`` the primary key (#276).

        Each column keeps its own ``unique``: it is not a key on its own, and
        Django adds its UNIQUE constraint.
        """
        keys = self._composite_primary_key(class_node)
        if not keys:
            return
        for f in entity.fields:
            if f.name in keys:
                f.is_primary_key = True
                f.is_nullable = False

    def _concrete_parents(self, class_node: ast.ClassDef) -> List[str]:
        """The concrete models ``class_node`` inherits a table link to, in base order.

        Each direct concrete base gets a parent link. A proxy base stands for
        the concrete model it proxies, and an abstract base passes on its own
        concrete parents, as in Django. A proxy has no table, so no links.
        """
        cached = self._parents_cache.get(class_node.name)
        if cached is not None:
            return cached
        parents: List[str] = []
        if not self._meta_flag(class_node, "proxy"):
            for parent in self._base_parents(class_node, (class_node.name,)):
                if parent not in parents:
                    parents.append(parent)
        self._parents_cache[class_node.name] = parents
        return parents

    def _base_parents(self, class_node: ast.ClassDef, stack: Tuple[str, ...]) -> List[str]:
        """The concrete parents contributed by ``class_node``'s direct bases.

        Memoized per class, so an abstract base shared along several
        inheritance paths is walked once; ``stack`` only guards cycles.
        """
        cached = self._base_parents_cache.get(class_node.name)
        if cached is not None:
            return cached
        parents: List[str] = []
        for base in self.classes.local_bases(class_node):
            if base in stack:
                continue
            concrete = self._concrete_model(base, stack)
            found = [concrete] if concrete is not None else []
            base_node = self.classes.all[base]
            if (
                concrete is None
                and self._inherits_django_model(base_node)
                and self._meta_flag(base_node, "abstract")
            ):
                found = self._base_parents(base_node, stack + (base,))
            parents.extend(p for p in found if p not in parents)  # each parent once
        self._base_parents_cache[class_node.name] = parents
        return parents

    def _concrete_model(self, name: str, stack: Tuple[str, ...]) -> str | None:
        """``name`` if it is a concrete model, the model a proxy stands for, else None."""
        if name in stack or name not in self.classes.all:
            return None
        if not self._is_concrete_django_model(name):
            return None
        node = self.classes.all[name]
        if not self._meta_flag(node, "proxy"):
            return name
        for base in self.classes.local_bases(node):
            concrete = self._concrete_model(base, stack + (name,))
            if concrete is not None:
                return concrete
        return None

    def _parent_links(self, class_node: ast.ClassDef) -> List[Tuple[str, str]]:
        """``(parent, link attribute)`` per concrete parent, in base order.

        The link is a ``OneToOneField(parent, parent_link=True)`` declared in
        the model or one of its abstract bases (the model's own wins), else
        the implicit ``<parent model name>_ptr``.
        """
        cached = self._links_cache.get(class_node.name)
        if cached is not None:
            return cached
        parents = self._concrete_parents(class_node)
        explicit: Dict[str, str] = {}
        if parents:
            # Effective declarations: a link removed (`place = None`) or
            # overridden by a plain field in a subclass no longer counts.
            for attr, (field_type, call, _) in self._own_declarations(class_node).items():
                if field_type == "OneToOneField" and self._has_true_kw(call, "parent_link"):
                    target = self._resolve_django_relationship_target(call, class_node.name)
                    if target is not None:
                        explicit[target] = attr
        links = [(parent, explicit.get(parent, f"{parent.lower()}_ptr")) for parent in parents]
        self._links_cache[class_node.name] = links
        return links

    def _add_parent_links(self, entity: EntityInfo, class_node: ast.ClassDef) -> None:
        """Add a one-to-one link column per concrete parent (multi-table inheritance).

        Like Django, the first link becomes the primary key unless the model
        declares one; the others are unique one-to-one columns. The primary
        key is listed first.
        """
        has_pk = any(f.is_primary_key for f in entity.fields)
        added: List[FieldInfo] = []
        links = self._parent_links(class_node)
        for parent, attr in links:
            is_pk = not has_pk
            has_pk = True
            declared = next((f for f in entity.fields if f.name == f"{attr}_id"), None)
            if declared is not None:  # an explicit parent_link field
                if is_pk:
                    declared.is_primary_key = True
                    declared.is_unique = False
                    declared.is_nullable = False
                continue
            column, type_str = self._django_target_column(parent, None, ())
            link = FieldInfo(
                name=f"{attr}_id",
                type_str=type_str,
                is_primary_key=is_pk,
                is_foreign_key=True,
                is_unique=not is_pk,
                foreign_table=f"{self._django_target_table(parent)}.{column}",
            )
            self._fk_targets[id(link)] = parent
            added.append(link)
        if links:
            fields = added + entity.fields
            entity.fields = [f for f in fields if f.is_primary_key] + [
                f for f in fields if not f.is_primary_key
            ]

    def _inherits_django_model(
        self, class_node: ast.ClassDef, visited: set[str] | None = None
    ) -> bool:
        """Check if a class inherits from Django's models.Model, directly or via ancestors."""
        visited = visited if visited is not None else set()
        if class_node.name in visited:
            return False
        visited.add(class_node.name)

        for base in class_node.bases:
            # models.Model / django.db.models.Model
            if isinstance(base, ast.Attribute) and base.attr == "Model":
                return True
            if isinstance(base, ast.Name):
                if base.id == "Model":
                    return True
                ancestor = self.classes.all.get(base.id)
                if ancestor is not None and self._inherits_django_model(ancestor, visited):
                    return True
        return False

    @staticmethod
    def _get_meta_class(class_node: ast.ClassDef) -> ast.ClassDef | None:
        """Return the nested ``class Meta`` of a Django model, if present."""
        for node in class_node.body:
            if isinstance(node, ast.ClassDef) and node.name == "Meta":
                return node
        return None

    def _meta_flag(self, class_node: ast.ClassDef, attr: str) -> bool:
        """Read a boolean attribute (e.g. ``abstract``) from a model's ``class Meta``."""
        value = self._meta_value(class_node, attr)
        return bool(value) if isinstance(value, bool) else False

    def _meta_value(self, class_node: ast.ClassDef, attr: str) -> object | None:
        """Read a constant attribute (e.g. ``db_table``) from a model's ``class Meta``.

        Plain and annotated assignments (``app_label: str = "sales"``) count;
        the last one wins, as in Python, and a non-literal last one makes the
        value unknown (None).
        """
        meta = self._get_meta_class(class_node)
        if meta is None:
            return None
        value: object | None = None
        for node in meta.body:
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets = [node.target]
            else:
                continue
            if any(isinstance(t, ast.Name) and t.id == attr for t in targets):
                assigned = node.value
                value = assigned.value if isinstance(assigned, ast.Constant) else None
        return value

    def _meta_constant(self, class_node: ast.ClassDef, attr: str) -> object | None:
        """A ``Meta`` option's constant value, also an inherited one (#279); else None."""
        value = self._meta_option(class_node, attr)
        return value.value if isinstance(value, ast.Constant) else None

    def _meta_option(self, class_node: ast.ClassDef, attr: str) -> ast.expr | None:
        """The expression a model's ``Meta`` assigns to ``attr``, as Django reads it (#279).

        Django pops ``class Meta`` off a model and puts it back on an abstract
        one only, so a model without its own ``Meta`` gets the nearest one in
        its MRO that is not a concrete model's: an abstract base's. Its own
        ``Meta`` inherits options only by subclassing (``class
        Meta(Base.Meta)``). Not for ``abstract``, which Django resets on an
        abstract base's ``Meta`` (:meth:`_meta_flag` reads the model's own).
        """
        meta = self._get_meta_class(class_node)
        if meta is None:
            for name in (self.classes.mro(class_node.name) or [class_node.name])[1:]:
                if self._is_concrete_django_model(name):
                    continue
                meta = self._get_meta_class(self.classes.all[name])
                if meta is not None:
                    break
        return self._meta_class_option(meta, attr, ()) if meta is not None else None

    def _meta_class_option(
        self, meta: ast.ClassDef, attr: str, stack: Tuple[int, ...]
    ) -> ast.expr | None:
        """``attr`` as a ``Meta`` class body sets it (the last assignment), else its bases'.

        A base is another model's ``Meta`` (``Base.Meta``) or a scanned class;
        anything else is unknown.
        """
        if id(meta) in stack:
            return None
        value: ast.expr | None = None
        for node in meta.body:
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets = [node.target]
            else:
                continue
            if any(isinstance(t, ast.Name) and t.id == attr for t in targets):
                value = node.value
        if value is not None:
            return value
        for base in meta.bases:
            base_meta: ast.ClassDef | None = None
            if (
                isinstance(base, ast.Attribute)
                and base.attr == "Meta"
                and isinstance(base.value, ast.Name)
                and base.value.id in self.classes.all
            ):
                base_meta = self._get_meta_class(self.classes.all[base.value.id])
            elif isinstance(base, ast.Name) and base.id in self.classes.all:
                base_meta = self.classes.all[base.id]
            if base_meta is not None:
                found = self._meta_class_option(base_meta, attr, stack + (id(meta),))
                if found is not None:
                    return found
        return None

    def _django_self_owner(self, name: str, merge_order: List[str]) -> str:
        """The model a Django ``"self"`` relation declared in class ``name`` points at.

        A concrete model's own fields point at that model (a multi-table child
        does not copy them, #233). An abstract base's or a plain
        mixin's fields are copied into the first concrete model that inherits
        it, so ``"self"`` points there (#226).
        """
        if self._is_concrete_django_model(name):
            return name
        for candidate in merge_order:  # root first, so the nearest concrete heir wins
            if (
                candidate != name
                and self._is_concrete_django_model(candidate)
                and name in (self.classes.mro(candidate) or ())
            ):
                return candidate
        return name

    def _is_concrete_django_model(self, name: str) -> bool:
        """A Django model with its own table: a ``models.Model`` subclass, not abstract.

        A plain mixin or an abstract base has no table, so a ``"self"``
        relation declared there belongs to the concrete model that copies it.
        """
        node = self.classes.all[name]
        return self._inherits_django_model(node) and not self._meta_flag(node, "abstract")

    def _django_declared_names(self, class_node: ast.ClassDef) -> List[str]:
        """Attribute names a Django model body declares or removes.

        A model field declares its name. ``name = None`` removes a field
        inherited from an abstract base, as Django documents, so it also drops
        whatever the bases stored under that name.
        """
        return [
            *(name for name, _, _ in self._django_field_calls(class_node)),
            *self._django_removed_names(class_node),
        ]

    @staticmethod
    def _django_removed_names(class_node: ast.ClassDef) -> List[str]:
        """Names a Django class body sets to ``None`` to remove an inherited field."""
        return [
            node.targets[0].id
            for node in class_node.body
            if isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant)
            and node.value.value is None
        ]

    def _extract_django_fields(
        self, class_node: ast.ClassDef, concrete: str
    ) -> Tuple[Dict[str, FieldInfo], Dict[str, _Rel]]:
        """Extract fields and relationships from a Django model.

        Django fields are plain assignments (``name = models.CharField(...)``),
        not annotated. ``ForeignKey`` / ``OneToOneField`` become ``<name>_id``
        foreign-key columns, ``ManyToManyField`` becomes a relationship, and
        every other ``*Field`` is a column. ``"self"`` names ``concrete``, the
        model being built, as in Django, where a relation to ``"self"`` in an
        abstract base points at each concrete subclass.
        """
        fields: Dict[str, FieldInfo] = {}
        relationships: Dict[str, _Rel] = {}

        for name, field_type, call in self._django_field_calls(class_node):
            if field_type in ("ForeignKey", "OneToOneField"):
                # Both are a real `<name>_id` column in the DB; model them as such
                # (like SQLAlchemy) so they render consistently across sources and
                # follow `null=` (#223). A OneToOneField is that column made unique,
                # or the PK itself with primary_key=True (shared primary key), in
                # which case Django adds no implicit `id` (#224).
                fk = self._parse_django_fk_column(
                    name, call, concrete, one_to_one=field_type == "OneToOneField"
                )
                if fk:
                    fields[fk.name] = fk
            elif field_type == "ManyToManyField":
                rel = self._parse_django_many_to_many(name, call, concrete)
                if rel:
                    relationships[name] = rel
            elif field_type == COMPOSITE_PRIMARY_KEY:
                continue  # no column; finish() marks the key's columns (#276)
            else:
                fields[name] = self._parse_django_column(name, field_type, call)

        return fields, relationships

    def _django_field_calls(self, class_node: ast.ClassDef) -> List[Tuple[str, str, ast.Call]]:
        """``(attribute, field class name, call)`` for each model field in a Django class body."""
        calls: List[Tuple[str, str, ast.Call]] = []
        for node in class_node.body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name) or target.id.startswith("_"):
                continue
            if not isinstance(node.value, ast.Call):
                continue
            field_type = self._django_field_type(node.value)
            if field_type is not None:
                calls.append((target.id, field_type, node.value))
        return calls

    @staticmethod
    def _has_true_kw(call: ast.Call, name: str) -> bool:
        """Whether ``call`` passes ``name=True`` as a literal keyword."""
        return any(
            kw.arg == name and isinstance(kw.value, ast.Constant) and kw.value.value is True
            for kw in call.keywords
        )

    def _parse_django_fk_column(
        self, name: str, call: ast.Call, current_class: str, *, one_to_one: bool = False
    ) -> FieldInfo | None:
        """Model a ``ForeignKey`` / ``OneToOneField`` as the ``<name>_id`` column it creates.

        A ``OneToOneField`` is a ``ForeignKey(unique=True)``.
        """
        target = self._resolve_django_relationship_target(call, current_class)
        if target is None:
            return None

        is_nullable = False
        is_unique = one_to_one
        is_primary_key = False
        for keyword in call.keywords:
            if not isinstance(keyword.value, ast.Constant):
                continue
            if keyword.arg == "null":
                is_nullable = bool(keyword.value.value)
            elif keyword.arg == "unique" and not one_to_one:
                is_unique = bool(keyword.value.value)
            elif keyword.arg == "primary_key":
                is_primary_key = bool(keyword.value.value)

        # ForeignKey(primary_key=True) makes `<name>_id` the table's primary key,
        # so Django adds no implicit `id` (#224). A PK is never NULL, and its
        # uniqueness is tracked by is_primary_key, not is_unique.
        to_field = self._django_to_field(call)
        # A to_field column of a multi-table parent lives in the parent's table.
        if to_field is not None:
            target = self._column_owner(target, to_field, ()) or target
        column, type_str = self._django_target_column(target, to_field, ())
        fk = FieldInfo(
            name=f"{name}_id",
            type_str=type_str,
            is_primary_key=is_primary_key,
            is_foreign_key=True,
            is_nullable=is_nullable and not is_primary_key,
            is_unique=is_unique,  # cleared on a sole primary key (#331)
            foreign_table=f"{self._django_target_table(target)}.{column}",
        )
        self._fk_targets[id(fk)] = target
        return fk

    def _column_owner(self, model: str, to_field: str, stack: Tuple[str, ...]) -> str | None:
        """The model whose table holds column ``to_field`` of ``model``, if any.

        That is ``model`` itself, or the multi-table parent declaring it.
        """
        node = self.classes.all.get(model)
        if node is None or model in stack:
            return None
        if to_field in self._own_column_names(node):
            return model
        for parent in self._concrete_parents(node):
            owner = self._column_owner(parent, to_field, stack + (model,))
            if owner is not None:
                return owner
        return None

    def _own_declarations(self, node: ast.ClassDef) -> Dict[str, _Declaration]:
        """The fields Django builds into the model's own table, by attribute.

        Django's ``ModelBase`` (#272, #280): the class body's fields, then,
        along the MRO, each *direct* base that is an abstract model adds the
        fields it has itself (its own and those it copied) unless the name is
        already taken. Every other class in the MRO only takes names: a
        concrete parent its fields (they stay in its table, #233), a plain
        mixin or an indirect ancestor every name its body binds. So a field on
        a plain mixin is no column, and a diamond keeps the first copy. A base
        that is not known to be plain (it extends a class outside the scanned
        files) is read like an abstract model.
        """
        cached = self._declarations.get(node.name)
        if cached is not None:
            return cached
        declared: Dict[str, _Declaration] = {}
        self._declarations[node.name] = declared  # a cyclic hierarchy finds it empty
        for attr, field_type, call in self._django_field_calls(node):
            declared.pop(attr, None)
            declared[attr] = (field_type, call, node.name)
        taken = self._body_names(node)
        direct = set(self.classes.local_bases(node))
        mro = self.classes.mro(node.name) or self.classes.dfs_order(node, set())[::-1]
        for base in mro:
            if base == node.name:
                continue
            base_node = self.classes.all[base]
            inherited = self._own_declarations(base_node)
            if self._is_concrete_django_model(base):
                # Its local fields, including the implicit `id` / `<x>_ptr` links.
                taken |= self._own_column_names(base_node)
                if base not in direct:
                    taken |= self._body_names(base_node)
            elif base not in direct or self._is_plain_class(base, ()):
                taken |= self._body_names(base_node) | set(inherited)
            else:
                for attr, declaration in inherited.items():
                    if attr not in declared and attr not in taken:
                        declared[attr] = declaration
        return declared

    @staticmethod
    def _body_names(node: ast.ClassDef) -> Set[str]:
        """Every name a class body binds (its ``__dict__``), ``name = None`` included.

        A bare annotation binds nothing, so it doesn't block an inherited field.
        """
        names: Set[str] = set()
        for stmt in node.body:
            if isinstance(stmt, ast.Assign):
                names.update(t.id for t in stmt.targets if isinstance(t, ast.Name))
            elif (
                isinstance(stmt, ast.AnnAssign)
                and stmt.value is not None
                and isinstance(stmt.target, ast.Name)
            ):
                # A bare annotation (`id: UUID`) only writes __annotations__.
                names.add(stmt.target.id)
            elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(stmt.name)
        names.discard("Meta")  # Django pops it off the class
        return names

    def _is_plain_class(self, name: str, stack: Tuple[str, ...]) -> bool:
        """Whether a class is known not to be a Django model.

        Every base is ``object``, ``Generic[...]``, ``Protocol``, ``ABC`` or a
        scanned plain class. Any other base outside the scanned files might be
        a model, so such a class is not known to be plain.
        """
        node = self.classes.all.get(name)
        if node is None or name in stack:
            return False
        for base in node.bases:
            inner = base.value if isinstance(base, ast.Subscript) else base  # Typed[str]
            if expr_name(inner) in _NON_MODEL_BASES:
                continue
            if not (
                isinstance(inner, ast.Name) and self._is_plain_class(inner.id, stack + (name,))
            ):
                return False
        return True

    def _own_column_names(self, node: ast.ClassDef) -> Set[str]:
        """Field names (and FK attnames) stored in the model's own table."""
        names: Set[str] = set()
        declared = self._own_declarations(node)
        for attr, (field_type, _, _) in declared.items():
            names.add(attr)
            if field_type in ("ForeignKey", "OneToOneField"):
                names.add(f"{attr}_id")
        links = self._parent_links(node)
        for _, link in links:
            names.update((link, f"{link}_id"))
        # Django's implicit `id`, when nothing else is the primary key.
        if not links and not any(
            field_type == COMPOSITE_PRIMARY_KEY or self._has_true_kw(call, "primary_key")
            for field_type, call, _ in declared.values()
        ):
            names.add("id")
        return names

    @staticmethod
    def _django_to_field(call: ast.Call) -> str | None:
        """The literal ``to_field=`` of a Django relationship field, if any."""
        for kw in call.keywords:
            if (
                kw.arg == "to_field"
                and isinstance(kw.value, ast.Constant)
                and isinstance(kw.value.value, str)
            ):
                return kw.value.value
        return None

    def _django_target_column(
        self, target: str, to_field: str | None, stack: Tuple[Tuple[str, str | None], ...]
    ) -> Tuple[str, str]:
        """Return the ``(column, type)`` a Django FK to ``target`` references (#226).

        That is the ``to_field`` column if given, else the target's primary key,
        including one inherited from a base. A key that is itself a foreign key
        is its ``<name>_id`` column, typed like the column *it* references. An
        unknown target, field or cycle falls back to ``id`` / ``to_field`` with
        Django's default ``BigAutoField`` type. A cycle is a repeated
        ``(model, to_field)`` lookup, so following a key to another column of
        the same model still resolves.
        """
        key = (target, to_field)
        cached = self._target_column_cache.get(key)
        if cached is not None:
            return cached
        # contrib apps (auth, contenttypes) keep AutoField primary keys.
        auto_field = "AutoField" if target in CONTRIB_TABLES else "BigAutoField"
        default = (to_field or "id", self._django_display_type(auto_field))
        node = self.classes.all.get(target)
        if node is None or key in stack:
            return default
        # A to_field column of a multi-table parent lives in the parent's table (#233).
        owner = self._column_owner(target, to_field, ()) if to_field is not None else None
        if owner is not None and owner != target:
            result = self._django_target_column(owner, to_field, stack + (key,))
        else:
            result = self._resolve_django_target_column(target, node, to_field, stack, default)
        self._target_column_cache[key] = result
        return result

    def _resolve_django_target_column(
        self,
        target: str,
        node: ast.ClassDef,
        to_field: str | None,
        stack: Tuple[Tuple[str, str | None], ...],
        default: Tuple[str, str],
    ) -> Tuple[str, str]:
        """Uncached body of :meth:`_django_target_column`."""

        merge_order = self.classes.merge_order(node)
        declared = self._own_declarations(node)

        if to_field is not None:
            attr = to_field
            # Django also accepts a relation's attname (`account_id` for `account`).
            if attr not in declared and attr.endswith("_id"):
                relation = declared.get(attr[: -len("_id")])
                if relation is not None and relation[0] in ("ForeignKey", "OneToOneField"):
                    attr = attr[: -len("_id")]
            if attr not in declared:
                # The implicit parent link (`place_ptr` / `place_ptr_id`), #233.
                for parent, link in self._parent_links(node):
                    if link not in declared and attr in (link, f"{link}_id"):
                        _, ref_type = self._django_target_column(
                            parent, None, stack + ((target, to_field),)
                        )
                        return f"{link}_id", ref_type
                return default
        else:
            pks = [
                a for a, (_, call, _) in declared.items() if self._has_true_kw(call, "primary_key")
            ]
            if not pks:
                links = self._parent_links(node)
                if not links:
                    return default
                # The first parent link is the primary key (multi-table inheritance).
                parent, link = links[0]
                if link not in declared:  # implicit `<parent>_ptr`
                    _, ref_type = self._django_target_column(
                        parent, None, stack + ((target, to_field),)
                    )
                    return f"{link}_id", ref_type
                pks = [link]
            attr = pks[-1]

        field_type, call, declaring = declared[attr]
        if field_type in ("ForeignKey", "OneToOneField"):
            # "self" binds like on the entity side (#226).
            owner = self._django_self_owner(declaring, merge_order)
            ref = self._resolve_django_relationship_target(call, owner)
            if ref is None:
                return f"{attr}_id", default[1]
            _, ref_type = self._django_target_column(
                ref, self._django_to_field(call), stack + ((target, to_field),)
            )
            return f"{attr}_id", ref_type
        return attr, self._parse_django_column(attr, field_type, call).type_str

    def _django_target_table(self, class_name: str) -> str:
        """Resolve a target class name to its table name.

        ``Meta.db_table`` or Django's default name for a parsed model; the real
        table of a ``django.contrib`` model (``auth.User`` -> ``auth_user``,
        #278); the lower-cased class name for any other model outside the
        parsed files, whose app is unknown.
        """
        node = self.classes.all.get(class_name)
        if node is None:
            return CONTRIB_TABLES.get(class_name, class_name.lower())
        db_table = self._meta_constant(node, "db_table")
        if isinstance(db_table, str):
            return db_table
        return self.default_table_name(node)

    @staticmethod
    def _django_field_type(call: ast.Call) -> str | None:
        """Return the Django field class name (e.g. "CharField", "ForeignKey").

        Only constructs that are relationship fields or end in "Field" qualify,
        which filters out non-field assignments such as ``objects = Manager()``.
        ``CompositePrimaryKey`` is returned too: a model field that makes no
        column (#276).
        """
        func = call.func
        if isinstance(func, ast.Attribute):
            name = func.attr
        elif isinstance(func, ast.Name):
            name = func.id
        else:
            return None
        if name in DJANGO_RELATIONSHIP_FIELDS or name.endswith("Field"):
            return name
        if name == COMPOSITE_PRIMARY_KEY:
            return name
        return None

    def _parse_django_column(self, name: str, field_type: str, call: ast.Call) -> FieldInfo:
        """Parse a Django column field (``models.CharField(...)``, etc.)."""
        is_primary_key = False
        is_nullable = False
        is_unique = False
        default_value = None

        for keyword in call.keywords:
            if keyword.arg == "primary_key" and isinstance(keyword.value, ast.Constant):
                is_primary_key = bool(keyword.value.value)
            elif keyword.arg == "null" and isinstance(keyword.value, ast.Constant):
                is_nullable = bool(keyword.value.value)
            elif keyword.arg == "unique" and isinstance(keyword.value, ast.Constant):
                is_unique = bool(keyword.value.value)
            elif keyword.arg == "default" and isinstance(keyword.value, ast.Constant):
                default_value = repr(keyword.value.value)

        # A choices= referencing a TextChoices/IntegerChoices class links the
        # column to that enum; otherwise show the mapped/raw field type.
        choices_enum = self._django_choices_enum(call)
        type_str = choices_enum if choices_enum else self._django_display_type(field_type)

        return FieldInfo(
            name=name,
            type_str=type_str,
            is_primary_key=is_primary_key,
            is_nullable=is_nullable and not is_primary_key,
            default_value=default_value,
            is_unique=is_unique,  # cleared on a sole primary key (#331)
        )

    def _django_choices_enum(self, call: ast.Call) -> str | None:
        """Return the enum class name a ``choices=`` argument references, if any.

        Handles ``choices=Status.choices`` and ``choices=Status``; the name must
        resolve to a known TextChoices/IntegerChoices/Enum class. Inline
        ``choices=[("a", "A"), ...]`` tuples are anonymous and not linked.
        """
        for keyword in call.keywords:
            if keyword.arg != "choices":
                continue
            node = keyword.value
            enum_name = None
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                enum_name = node.value.id  # Status.choices -> Status
            elif isinstance(node, ast.Name):
                enum_name = node.id  # choices=Status
            if (
                enum_name
                and enum_name in self.classes.all
                and is_enum_class(self.classes.all[enum_name], self.classes.all)
            ):
                return enum_name
        return None

    def _django_display_type(self, field_type: str) -> str:
        """Map a Django field type to a readable Python type.

        Falls back to the original Django field name for ambiguous/unknown fields,
        or always returns it when ``--django-raw-types`` is set.
        """
        if self.ctx.django_raw_types:
            return field_type
        return DJANGO_FIELD_TYPE_MAP.get(field_type, field_type)

    def _parse_django_many_to_many(
        self, name: str, call: ast.Call, current_class: str
    ) -> _Rel | None:
        """Parse a Django ``ManyToManyField`` into a relationship tuple.

        ``ForeignKey`` / ``OneToOneField`` are FK columns instead (see
        :meth:`_parse_django_fk_column`). ``ManyToManyField(through=...)`` is
        skipped - that M:N is drawn through the through-model's own foreign
        keys, exactly like SQLAlchemy ``secondary=``.
        """
        target = self._resolve_django_relationship_target(call, current_class)
        if target is None:
            return None
        if any(keyword.arg == "through" for keyword in call.keywords):
            return None
        # A contrib target stays qualified ("auth.Group"): contrib models aren't
        # drawn, and a project model sharing the class name must not get the edge.
        return _Rel(target, "many_to_many", name, False)

    def _resolve_django_relationship_target(self, call: ast.Call, current_class: str) -> str | None:
        """Resolve a relationship field's target from its first positional or ``to=`` arg.

        A model name in a string reference is case-insensitive, as in Django
        (``"catalog.author"`` is ``Author``). A proxy model has no table, so a
        relation to it targets the concrete model it proxies.
        """
        target = None
        bindings = self._module_bindings(call)
        if call.args:
            target = self._resolve_django_target(call.args[0], current_class, bindings)
        else:
            for keyword in call.keywords:
                if keyword.arg == "to":
                    target = self._resolve_django_target(keyword.value, current_class, bindings)
                    break
        if target is not None and "." not in target and target not in self.classes.all:
            target = self._class_names_by_lower().get(target.lower(), target)
        if target is not None and target in self.classes.all:
            if self._meta_flag(self.classes.all[target], "proxy"):
                return self._concrete_model(target, ()) or target
        return target

    def _class_names_by_lower(self) -> Dict[str, str]:
        """Lower-cased name -> class name, for names that are unambiguous that way."""
        if self._lower_names is None:
            counts: Dict[str, List[str]] = {}
            for name in self.classes.all:
                counts.setdefault(name.lower(), []).append(name)
            self._lower_names = {low: names[0] for low, names in counts.items() if len(names) == 1}
        return self._lower_names

    def _resolve_django_target(
        self, node: ast.expr, current_class: str, bindings: Dict[str, str]
    ) -> str | None:
        """Resolve a Django relationship target to a class name.

        Handles ``"self"``, ``"app.Model"`` / ``"Model"`` string references and a
        direct class reference (``ForeignKey(Author, ...)``). A ``django.contrib``
        model is returned qualified (``"auth.User"``): from a string naming its
        app, a name the declaring module imports from contrib (``bindings``;
        it wins over a scanned class of the same name), or the user model
        (``settings.AUTH_USER_MODEL``, ``get_user_model()``, #278).
        """
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value
            if value == "self":
                return current_class
            return contrib_target(value) or value.split(".")[-1]
        if isinstance(node, ast.Attribute) and node.attr == "AUTH_USER_MODEL":
            return self._user_model()
        if isinstance(node, ast.Call) and expr_name(node.func) == "get_user_model":
            return self._user_model()
        if isinstance(node, ast.Name) and node.id in bindings:
            return bindings[node.id]
        return expr_name(node)

    def _module_bindings(self, call: ast.Call) -> Dict[str, str]:
        """Contrib names the declaring module binds where the field ``call`` is declared.

        The declaring class may be an abstract base in another file than the
        model being built, so its own module's imports are the ones that count.
        """
        if self._declaring is None:
            self._declaring = {
                id(node): owner
                for owner in self.classes.all.values()
                for node in ast.walk(owner)
                if isinstance(node, ast.Call)
            }
        owner = self._declaring.get(id(call))
        tree = self.ctx.tree_of(owner) if owner is not None else None
        if owner is None or tree is None:
            return {}
        # The bindings where the class is declared: a later rebinding of the
        # name doesn't change a field that already captured it.
        key = (id(tree), owner.lineno)
        if key not in self._bindings:
            self._bindings[key] = contrib_bindings(tree, owner.lineno)
        return self._bindings[key]

    def _user_model(self) -> str:
        """The model ``AUTH_USER_MODEL`` names, as far as the source tells.

        The one scanned concrete model built on ``AbstractBaseUser`` (also via
        ``AbstractUser``), else Django's default ``auth.User``. The setting
        itself lives in ``settings.py``, which erdify doesn't read.
        """
        if self._user_model_name is None:
            # Root user models only: a proxy or multi-table child of the user
            # model builds on AbstractBaseUser too, but is not another candidate.
            users = [
                name
                for name, node in self.classes.all.items()
                if self.ctx.file_of(node) is not None
                and self._is_concrete_django_model(name)
                and not self._meta_flag(node, "proxy")
                and not self._concrete_parents(node)
                and self._builds_on(node, "AbstractBaseUser", set())
            ]
            self._user_model_name = users[0] if len(users) == 1 else DEFAULT_USER_MODEL
        return self._user_model_name

    def _builds_on(self, node: ast.ClassDef, base_name: str, seen: Set[str]) -> bool:
        """Whether ``base_name`` is among the class's ancestors (by name)."""
        for base in node.bases:
            name = expr_name(base)
            if name is None or name in seen:
                continue
            seen.add(name)
            if name == base_name:
                return True
            parent = self.classes.all.get(name)
            if parent is not None and self._builds_on(parent, base_name, seen):
                return True
        return False


def _literal_names(node: ast.expr) -> Tuple[str, ...] | None:
    """The strings of a list / tuple of string literals, else None."""
    if not isinstance(node, (ast.List, ast.Tuple)):
        return None
    names = [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    return tuple(names) if len(names) == len(node.elts) else None
