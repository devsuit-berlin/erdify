"""Django reference loader: build a :class:`Schema` from ``Model._meta``.

The source is executed inside an isolated app registry
(``django.test.utils.isolate_apps``), so every snippet gets a clean registry
and models with the same name in different snippets never collide. No database
is touched: everything compared here comes from model metadata.
"""

from __future__ import annotations

import re
from typing import Any

import django
from django.apps import apps as global_apps
from django.conf import settings
from django.core.exceptions import FieldError
from django.db import models
from django.test.utils import isolate_apps

from .schema import Column, Schema, Table

APP = "tests.ground_truth.django_app"
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


# A string relation target: the first argument of a relation field, or ``to=``
# / ``through=``. Other dotted strings (``db_table = "schema.table"``) are kept.
_LAZY_REFERENCE = re.compile(r"""(\(|\b(?:to|through)\s*=)(\s*)(["'])(\w+)\.(\w+)\3""")


def _single_app(source: str) -> str:
    """Drop the app label from ``"app.Model"`` lazy references.

    Every source is loaded as one app, so a reference naming its own app
    (``"catalog.Place"``) resolves the same way without the label. Django
    matches the model name case-insensitively either way. References into the
    ``CONTRIB`` apps (``"auth.User"``) are kept.
    """

    def strip(match: re.Match[str]) -> str:
        prefix, space, quote, label, model = match.groups()
        target = f"{label}.{model}" if label in CONTRIB else model
        return f"{prefix}{space}{quote}{target}{quote}"

    return _LAZY_REFERENCE.sub(strip, source)


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
            exec(compile(_single_app(source), "<models>", "exec"), namespace)
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
        # ``__empty__`` is the label of a blank form choice, not a stored value.
        name: tuple(n for n in value.names if n != "__empty__")
        for name, value in namespace.items()
        if isinstance(value, type)
        and issubclass(value, models.Choices)
        and value.__module__ == namespace["__name__"]
    }
    return Schema(tables=tables, enums=enums)


def table_name(model: type[models.Model]) -> str:
    """The table name erdify is expected to show for ``model``.

    Django prefixes a default table name with the app label
    (``<app_label>_<model>``); erdify has no app configuration and shows the
    bare name, so the prefix is dropped here until #271 decides whether erdify
    should add it. An explicit ``Meta.db_table`` is compared as-is.
    """
    meta = model._meta
    if "db_table" in meta.original_attrs:
        return str(meta.db_table)
    return meta.db_table.removeprefix(f"{meta.app_label}_")


def _table(model: type[models.Model]) -> Table:
    meta = model._meta
    # pk_fields covers a CompositePrimaryKey (Django 5.2+), whose columns
    # don't set primary_key themselves.
    pk_fields = set(meta.pk_fields)
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
            unique=f.unique and f not in pk_fields,
            fk=fk,
        )
    m2m = frozenset(
        (f.name, f.related_model._meta.concrete_model.__name__)
        for f in meta.local_many_to_many
        if f.remote_field.through._meta.auto_created
    )
    return Table(table=table_name(model), columns=columns, m2m=m2m)
