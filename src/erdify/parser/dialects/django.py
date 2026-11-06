"""Django ORM: ``models.Model`` subclasses with ``*Field`` class attributes."""

import ast
from typing import Dict, List, Set, Tuple

from ...config import EntityInfo, FieldInfo
from ..annotations import expr_name
from ..common import _Rel, is_enum_class, to_snake_case
from .base import Dialect, ParseContext

#: Django relationship field constructs (everything else ending in "Field" is a column).
DJANGO_RELATIONSHIP_FIELDS = frozenset({"ForeignKey", "OneToOneField", "ManyToManyField"})

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
        self._links_cache: Dict[str, List[Tuple[str, str]]] = {}

    def detect(self, class_node: ast.ClassDef) -> bool:
        return self._inherits_django_model(class_node)

    def is_drawable(self, class_node: ast.ClassDef) -> bool:
        return not (self._meta_flag(class_node, "abstract") or self._meta_flag(class_node, "proxy"))

    def table_name(self, class_node: ast.ClassDef) -> str | None:
        """``__tablename__`` if set, else ``class Meta: db_table = "..."``."""
        table_name = super().table_name(class_node)
        if not table_name:
            db_table = self._meta_value(class_node, "db_table")
            if isinstance(db_table, str):
                table_name = db_table
        return table_name

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

    def drop_on_merge(
        self,
        fields: Dict[str, FieldInfo],
        rels: Dict[str, _Rel],
        attr: str,
        class_fields: Dict[str, FieldInfo],
        class_rels: Dict[str, _Rel],
    ) -> None:
        """Drop whatever earlier classes stored for a redeclared Django attribute.

        A Django attribute is stored under a key that depends on its kind
        (relationship ``owner`` vs. FK column ``owner_id``, #224), so all of
        them go.
        """
        rels.pop(attr, None)
        fields.pop(attr, None)
        inherited_fk = fields.get(f"{attr}_id")
        if inherited_fk is not None and inherited_fk.is_foreign_key:
            del fields[f"{attr}_id"]

    def drop_on_listing(
        self, fields: Dict[str, FieldInfo], rels: Dict[str, _Rel], attr: str
    ) -> None:
        """A Django body's redeclaration moves the attribute to the body's position."""
        self.drop_on_merge(fields, rels, attr, {}, {})

    def finish(self, entity: EntityInfo, class_node: ast.ClassDef) -> None:
        """Add the parent links and Django's implicit ``id`` primary key."""
        super().finish(entity, class_node)
        self._add_parent_links(entity, class_node)
        # Django implicitly adds an `id` primary key (BigAutoField since Django 3.2)
        # when no field declares primary_key=True and there is no parent link.
        if not any(f.is_primary_key for f in entity.fields):
            entity.fields.insert(
                0,
                FieldInfo(
                    name="id",
                    type_str=self._django_display_type("BigAutoField"),
                    is_primary_key=True,
                ),
            )

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
            merge_order = self.classes.merge_order(class_node)
            own = self.table_classes(class_node, merge_order)
            for class_name in merge_order:  # root first, so the model's own body wins
                if class_name not in own:
                    continue
                for attr, field_type, call in self._django_field_calls(
                    self.classes.all[class_name]
                ):
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
            added.append(
                FieldInfo(
                    name=f"{attr}_id",
                    type_str=type_str,
                    is_primary_key=is_pk,
                    is_foreign_key=True,
                    is_unique=not is_pk,
                    foreign_table=f"{self._django_target_table(parent)}.{column}",
                )
            )
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
        """Read a constant attribute (e.g. ``db_table``) from a model's ``class Meta``."""
        meta = self._get_meta_class(class_node)
        if meta is None:
            return None
        for node in meta.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == attr:
                        return node.value.value
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
        return FieldInfo(
            name=f"{name}_id",
            type_str=type_str,
            is_primary_key=is_primary_key,
            is_foreign_key=True,
            is_nullable=is_nullable and not is_primary_key,
            is_unique=is_unique and not is_primary_key,
            foreign_table=f"{self._django_target_table(target)}.{column}",
        )

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

    def _own_declarations(self, node: ast.ClassDef) -> Dict[str, Tuple[str, ast.Call, str]]:
        """The winning ``(field type, call, declaring class)`` of each attribute in the table.

        Resolved like the fields (#228), after removals (``name = None``) and
        overrides; a concrete parent's fields live in the parent's table (#233).
        """
        merge_order = self.classes.merge_order(node)
        own = self.table_classes(node, merge_order)
        declared: Dict[str, Tuple[str, ast.Call, str]] = {}
        for class_name in merge_order:
            if class_name not in own:
                continue
            class_node = self.classes.all[class_name]
            for attr in self._django_removed_names(class_node):
                declared.pop(attr, None)
            for attr, field_type, call in self._django_field_calls(class_node):
                declared.pop(attr, None)
                declared[attr] = (field_type, call, class_name)
        return declared

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
            self._has_true_kw(call, "primary_key") for _, call, _ in declared.values()
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
        default = (to_field or "id", self._django_display_type("BigAutoField"))
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
        """Resolve a target class name to its table name (Meta.db_table or snake_case)."""
        node = self.classes.all.get(class_name)
        if node is not None:
            db_table = self._meta_value(node, "db_table")
            if isinstance(db_table, str):
                return db_table
        return to_snake_case(class_name)

    @staticmethod
    def _django_field_type(call: ast.Call) -> str | None:
        """Return the Django field class name (e.g. "CharField", "ForeignKey").

        Only constructs that are relationship fields or end in "Field" qualify,
        which filters out non-field assignments such as ``objects = Manager()``.
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
            is_unique=is_unique and not is_primary_key,
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
                and is_enum_class(self.classes.all[enum_name])
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
        return (target, "many_to_many", name, False)

    def _resolve_django_relationship_target(self, call: ast.Call, current_class: str) -> str | None:
        """Resolve a relationship field's target from its first positional or ``to=`` arg.

        A proxy model has no table, so a relation to it targets the concrete
        model it proxies, as in Django.
        """
        target = None
        if call.args:
            target = self._resolve_django_target(call.args[0], current_class)
        else:
            for keyword in call.keywords:
                if keyword.arg == "to":
                    target = self._resolve_django_target(keyword.value, current_class)
                    break
        if target is not None and target in self.classes.all:
            if self._meta_flag(self.classes.all[target], "proxy"):
                return self._concrete_model(target, ()) or target
        return target

    @staticmethod
    def _resolve_django_target(node: ast.expr, current_class: str) -> str | None:
        """Resolve a Django relationship target to a class name.

        Handles ``"self"``, ``"app.Model"`` / ``"Model"`` string references and a
        direct class reference (``ForeignKey(Author, ...)``).
        """
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value
            if value == "self":
                return current_class
            return value.split(".")[-1]
        return expr_name(node)
