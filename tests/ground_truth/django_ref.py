"""Django reference loader: build a :class:`Schema` from ``Model._meta``.

The source is executed inside an isolated app registry
(``django.test.utils.isolate_apps``), so every snippet gets a clean registry
and models with the same name in different snippets never collide. No database
is touched: everything compared here comes from model metadata.
"""

from __future__ import annotations

import ast
import enum
from collections.abc import Iterable, Iterator
from typing import Any

import django
from django.apps import apps as global_apps
from django.conf import settings
from django.core.exceptions import FieldError
from django.db import models
from django.test.utils import isolate_apps

from .schema import Column, Schema, Table

APP = "tests.ground_truth.django_app"
APP_LABEL = "gt"  # see django_app/apps.py
# Django apps a model source may point at (user model, generic relations).
CONTRIB = {"contenttypes": "django.contrib.contenttypes", "auth": "django.contrib.auth"}


class Unloadable(Exception):
    """The source is not a complete Django model module on its own.

    Raised only for sources that reference names or models outside themselves
    (``NameError`` / ``ImportError`` / ``SyntaxError`` from a ``str.format``
    template or a third-party import, or a relation target that is not
    defined), which Django cannot load but erdify handles by design. Any other
    exception propagates and fails the test, so a broken harness or a Django
    API change can't turn comparisons into silent skips.
    """


class Rejected(Unloadable):
    """Django refuses the models (``FieldError``, or ``TypeError`` from model
    class creation, e.g. a proxy without a concrete base).

    erdify still draws such sources; there is no schema to compare them with.
    System-check errors that leave the schema defined (e.g. clashing reverse
    accessors, a missing ``max_length``) are deliberately not treated as
    rejections, so the regression snippets that contain them are still compared.
    """


def _setup() -> None:
    if not settings.configured:
        settings.configure(
            INSTALLED_APPS=[*CONTRIB.values(), APP],
            DEFAULT_AUTO_FIELD="django.db.models.AutoField",
        )
        django.setup()


RELATION_FIELDS = {"ForeignKey", "OneToOneField", "ManyToManyField", "ForeignObject"}


class _SingleApp(ast.NodeTransformer):
    """Drop the app label from ``"app.Model"`` relation targets.

    Every source is loaded as one app, so a reference naming its own app
    (``"catalog.Place"``) resolves the same way without the label. Django
    matches the model name case-insensitively either way. Only the target (first
    argument, ``to=``) and ``through=`` of a relation field are touched; other
    dotted strings (``db_table = "schema.table"``) and references into the
    ``CONTRIB`` apps (``"auth.User"``) are kept.
    """

    def visit_Call(self, node: ast.Call) -> ast.Call:
        self.generic_visit(node)
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if name in RELATION_FIELDS:
            targets = node.args[:1] + [k.value for k in node.keywords if k.arg in ("to", "through")]
            for target in targets:
                if (
                    isinstance(target, ast.Constant)
                    and isinstance(target.value, str)
                    and target.value.count(".") == 1
                ):
                    label, model = target.value.split(".")
                    if label not in CONTRIB:
                        target.value = model
        return node


def load(source: str) -> Schema:
    """Execute ``source`` as a Django models module and normalise its models."""
    _setup()
    namespace: dict[str, Any] = {"__name__": f"{APP}.models_under_test"}
    with isolate_apps(APP) as registry:
        # Make the contrib models resolvable from the isolated registry.
        for label in CONTRIB:
            for model in global_apps.get_app_config(label).get_models(include_auto_created=True):
                registry.all_models[label][model._meta.model_name] = model
        try:
            tree = _SingleApp().visit(ast.parse(source))
            exec(compile(tree, "<models>", "exec"), namespace)
        except (NameError, ImportError, SyntaxError) as exc:
            raise Unloadable(f"{type(exc).__name__}: {exc}") from exc
        except (FieldError, TypeError) as exc:
            raise Rejected(f"{type(exc).__name__}: {exc}") from exc
        concrete = [
            m
            for m in registry.get_models()
            if m.__module__ == namespace["__name__"] and not m._meta.proxy
        ]
        for model in concrete:
            for f in model._meta.get_fields(include_hidden=True):
                if f.is_relation and isinstance(f.related_model, str):
                    raise Unloadable(f"unresolved relation {model.__name__}.{f.name}")
        try:
            tables = {m.__name__: _table(m) for m in concrete}
        except FieldError as exc:
            raise Rejected(f"FieldError: {exc}") from exc
    enums = {
        cls.__name__: tuple(m for m in cls.__members__ if m != "__empty__")
        for cls in _classes(namespace.values(), namespace["__name__"])
        if issubclass(cls, enum.Enum)
    }
    return Schema(tables=tables, enums=enums)


def _classes(values: Iterable[object], module: str) -> Iterator[type]:
    """Every class defined in the source, including ones nested in a class body.

    Enums count whether they are ``models.Choices`` (often nested in the model,
    as Django's docs show) or a plain ``enum.Enum``, matching what erdify
    renders. ``__empty__`` is the label of a blank form choice, not a stored
    value, so it is left out.
    """
    for value in values:
        if isinstance(value, type) and value.__module__ == module:
            yield value
            yield from _classes(vars(value).values(), module)


def table_name(model: type[models.Model]) -> str:
    """The table name erdify is expected to show for ``model``.

    Django prefixes a default table name with the app label
    (``<app_label>_<model>``); erdify has no app configuration and shows the
    bare name, so the prefix of the source's own app is dropped here until #271
    decides whether erdify should add it. An explicit ``Meta.db_table`` and the
    tables of external (``CONTRIB``) models are compared as-is.
    """
    meta = model._meta
    if "db_table" in meta.original_attrs or meta.app_label != APP_LABEL:
        return str(meta.db_table)
    return meta.db_table.removeprefix(f"{APP_LABEL}_")


def _meta_unique(model: type[models.Model]) -> set[Any]:
    """Fields made unique on their own by ``Meta`` rather than ``unique=True``.

    An unconditional single-field ``UniqueConstraint`` or a one-field
    ``unique_together`` entry makes the column unique in the database without
    setting ``Field.unique``. Members of composite, conditional or expression
    constraints are not unique individually.
    """
    meta = model._meta
    names = [
        c.fields[0]
        for c in meta.constraints
        if isinstance(c, models.UniqueConstraint)
        and len(c.fields) == 1
        and c.condition is None
        and not c.expressions
    ]
    names += [group[0] for group in meta.unique_together if len(group) == 1]
    return {meta.get_field(name) for name in names}


def _table(model: type[models.Model]) -> Table:
    meta = model._meta
    # pk_fields covers a CompositePrimaryKey (Django 5.2+), whose columns
    # don't set primary_key themselves.
    pk_fields = set(meta.pk_fields)
    unique_fields = {f for f in meta.local_concrete_fields if f.unique} | _meta_unique(model)
    columns: dict[str, Column] = {}
    for f in meta.local_concrete_fields:
        fk = None
        if f.is_relation and (f.many_to_one or f.one_to_one):
            target = f.target_field
            fk = f"{table_name(target.model._meta.concrete_model)}.{target.column}"
        columns[f.column] = Column(
            pk=f in pk_fields,
            # A primary key is NOT NULL in the database even with null=True
            # (Django flags that as fields.E007 but still builds the column).
            nullable=f.null and f not in pk_fields,
            unique=f in unique_fields and f not in pk_fields,
            fk=fk,
        )
    m2m = frozenset(
        (f.name, f.related_model._meta.concrete_model.__name__)
        for f in meta.local_many_to_many
        if f.remote_field.through._meta.auto_created
    )
    return Table(table=table_name(model), columns=columns, m2m=m2m)
