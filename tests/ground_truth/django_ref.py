"""Django reference loader: build a :class:`Schema` from ``Model._meta``.

The source is executed inside an isolated app registry
(``django.test.utils.isolate_apps``), so every snippet gets a clean registry
and models with the same name in different snippets never collide. No database
is touched: everything compared here comes from model metadata.
"""

from __future__ import annotations

import ast
import enum
import types
from unittest import mock
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

import django
from django.apps import AppConfig
from django.apps import apps as global_apps
from django.apps.registry import Apps
from django.conf import settings
from django.contrib.auth.checks import check_models_permissions, check_user_model
from django.contrib.contenttypes.checks import (
    check_generic_foreign_keys,
    check_model_name_lengths,
)
from django.core.checks.model_checks import check_all_models
from django.core.exceptions import FieldError
from django.db import models
from django.test.utils import isolate_apps, override_settings

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
    accessors, a missing ``max_length``) are not rejections: they are reported
    in :attr:`Schema.checks`, and a source with any fails its test unless
    ``EXPECTED_CHECK_ERRORS`` lists them.
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
    """Execute ``source`` as a Django models module and normalise its models.

    The source is loaded the way a project would run it: the contrib apps are
    installed, and ``AUTH_USER_MODEL`` points at the source's own user model
    if it defines one (:func:`_user_model`). Django's system checks run on the
    models, and their error ids are returned in :attr:`Schema.checks`.
    """
    _setup()
    namespace: dict[str, Any] = {"__name__": f"{APP}.models_under_test"}
    try:
        tree = _SingleApp().visit(ast.parse(source))
    except SyntaxError as exc:
        raise Unloadable(f"SyntaxError: {exc}") from exc
    user_model = _user_model(tree)
    user_label = f"{_model_app_label(tree, user_model)}.{user_model}" if user_model else None
    swap = override_settings(AUTH_USER_MODEL=user_label) if user_label else None
    labels = sorted(_app_labels(tree) - {APP_LABEL, *CONTRIB})
    with isolate_apps(APP, *CONTRIB.values(), *map(_label_config, labels)) as registry:
        # The contrib modules were imported (and their models registered) by
        # django.setup(); make them part of the isolated registry too.
        for label in CONTRIB:
            for model in global_apps.get_app_config(label).get_models(include_auto_created=True):
                registry.all_models[label][model._meta.model_name] = model
        # get_user_model() looks the user model up in the global registry,
        # which doesn't hold the source's models: resolve it in the isolated one.
        lookup = mock.patch(
            "django.contrib.auth.get_user_model",
            lambda: registry.get_model(settings.AUTH_USER_MODEL),
        )
        if swap is not None:
            swap.enable()
            lookup.start()
        try:
            return _load(tree, namespace, registry, [APP_LABEL, *labels])
        finally:
            if swap is not None:
                lookup.stop()
                swap.disable()
            # The isolated registry wrote reverse-relation caches into the
            # shared contrib models' _meta (auth.User, ContentType, ...).
            global_apps.clear_cache()


def _load(tree: ast.Module, namespace: dict[str, Any], registry: Apps, labels: list[str]) -> Schema:
    try:
        exec(compile(tree, "<models>", "exec"), namespace)
    except (NameError, ImportError) as exc:
        raise Unloadable(f"{type(exc).__name__}: {exc}") from exc
    except (FieldError, TypeError) as exc:
        raise Rejected(f"{type(exc).__name__}: {exc}") from exc
    # all_models, not get_models(): a model with Meta.app_label naming an
    # app that isn't installed is registered but not listed by get_models().
    defined = [
        m
        for models_by_name in registry.all_models.values()
        for m in models_by_name.values()
        if m.__module__ == namespace["__name__"]
    ]
    concrete = [
        m
        for m in defined
        if not m._meta.proxy and not m._meta.abstract and not m._meta.auto_created
    ]
    for model in concrete:
        for f in model._meta.get_fields(include_hidden=True):
            if f.is_relation and isinstance(f.related_model, str):
                raise Unloadable(f"unresolved relation {model.__name__}.{f.name}")
    try:
        tables = {m.__name__: _table(m) for m in concrete}
        checks = _system_checks(registry, labels)
    except FieldError as exc:
        raise Rejected(f"FieldError: {exc}") from exc
    enums = {
        cls.__name__: tuple(m for m in cls.__members__ if m != "__empty__")
        for cls in _classes(namespace.values(), namespace["__name__"])
        if issubclass(cls, enum.Enum)
    }
    return Schema(tables=tables, enums=enums, checks=tuple(checks))


def _system_checks(registry: Apps, labels: list[str]) -> list[str]:
    """Error ids of Django's ``models`` checks for the source's apps.

    The checks ``manage.py check`` runs under the ``models`` tag, given the
    source's app configs: Django's per-model and cross-model checks (e.g.
    ``models.E028``) and those of the contrib apps (auth's user model and
    permissions, contenttypes' generic relations and name lengths). Not the
    whole tag: ``check_lazy_references`` reads the global registry. A check
    that crashes (a user model without ``USERNAME_FIELD``) would break
    ``manage.py check`` too and counts as an error, ``<check>.crashed``.
    ``labels`` are the apps the source's models live in.
    """
    app_configs = [registry.get_app_config(label) for label in labels]
    ids: set[str] = set()
    for check in MODEL_CHECKS:
        try:
            ids.update(e.id for e in check(app_configs=app_configs) if e.is_serious())
        except Exception:  # noqa: BLE001 - any crash makes the project's check fail
            ids.add(f"{check.__module__.rpartition('.')[0]}.{check.__name__}.crashed")
    return sorted(ids)


def _app_labels(tree: ast.Module) -> set[str]:
    """Literal ``Meta.app_label`` values of the source's classes."""
    labels: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Meta":
            for stmt in node.body:
                value = getattr(stmt, "value", None)
                targets = getattr(stmt, "targets", None) or [getattr(stmt, "target", None)]
                if (
                    isinstance(value, ast.Constant)
                    and isinstance(value.value, str)
                    and any(isinstance(t, ast.Name) and t.id == "app_label" for t in targets)
                ):
                    labels.add(value.value)
    return labels


def _label_config(label: str) -> AppConfig:
    """An installed app with label ``label`` for models that name it in ``Meta.app_label``.

    Like a project, where such a model's app would be in ``INSTALLED_APPS``;
    a module object is enough, nothing is imported.
    """
    module = types.ModuleType(f"{APP}_{label}")
    module.__path__ = [str(Path(__file__).parent)]
    config_class = type("SourceAppConfig", (AppConfig,), {"label": label})
    return config_class(module.__name__, module)


#: The ``models``-tag checks run for a source (see :func:`_system_checks`).
MODEL_CHECKS = (
    check_all_models,
    check_user_model,
    check_models_permissions,
    check_generic_foreign_keys,
    check_model_name_lengths,
)

USER_BASES = {"AbstractUser", "AbstractBaseUser"}


def _model_app_label(tree: ast.Module, name: str) -> str:
    """The app label the source's class ``name`` is registered under.

    Its own literal ``Meta.app_label``, else one inherited from a base of the
    source (an abstract base's ``Meta``), else the source's app.
    """
    classes = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
    pending, seen = [name], set()
    while pending:
        node = classes.get(pending.pop(0))
        if node is None or node.name in seen:
            continue
        seen.add(node.name)
        for label in _app_labels(ast.Module(body=[node], type_ignores=[])):
            return label
        pending.extend(getattr(b, "id", "") for b in node.bases)
    return APP_LABEL


def _user_model(tree: ast.Module) -> str | None:
    """The source's own user model, if it defines exactly one (by its bases).

    A root model on ``AbstractUser`` / ``AbstractBaseUser`` (also through
    classes of the source); not abstract, not a proxy, not a subclass of
    another user model. Read from the syntax tree, because ``AUTH_USER_MODEL``
    must be set before the models are created.
    """
    classes = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}

    def bases(node: ast.ClassDef) -> list[str]:
        return [
            b.attr if isinstance(b, ast.Attribute) else getattr(b, "id", "") for b in node.bases
        ]

    def is_user(name: str, seen: frozenset[str] = frozenset()) -> bool:
        node = classes.get(name)
        if node is None or name in seen:
            return name in USER_BASES
        return any(is_user(b, seen | {name}) for b in bases(node))

    def meta_flag(node: ast.ClassDef, flag: str) -> bool:
        for item in node.body:
            if isinstance(item, ast.ClassDef) and item.name == "Meta":
                for stmt in item.body:
                    if (
                        isinstance(stmt, ast.Assign)
                        and any(isinstance(t, ast.Name) and t.id == flag for t in stmt.targets)
                        and isinstance(stmt.value, ast.Constant)
                    ):
                        return stmt.value.value is True
        return False

    users = [
        name
        for name, node in classes.items()
        if name not in USER_BASES
        and is_user(name)
        and not meta_flag(node, "abstract")
        and not meta_flag(node, "proxy")
        # A subclass of another concrete user model (multi-table) isn't a root;
        # an abstract user base of the source is just a base.
        and not any(
            b in classes and is_user(b) and not meta_flag(classes[b], "abstract")
            for b in bases(node)
        )
    ]
    return users[0] if len(users) == 1 else None


def _classes(values: Iterable[object], module: str) -> Iterator[type]:
    """Every class defined in the source, including ones nested in a class body.

    Enums count whether they are ``models.Choices`` (often nested in the model,
    as Django's docs show) or a plain ``enum.Enum``, matching what erdify
    renders. ``__empty__`` is the label of a blank form choice, not a stored
    value, so it is left out.
    """
    seen: set[type] = set()
    pending = list(values)
    while pending:
        value = pending.pop()
        if isinstance(value, type) and value.__module__ == module and value not in seen:
            seen.add(value)  # class attributes may refer back (``Node.alias = Node``)
            yield value
            pending.extend(vars(value).values())


def table_name(model: type[models.Model]) -> str:
    """The real table name: ``Meta.db_table`` or ``<app_label>_<model name>``."""
    return str(model._meta.db_table)


def _model_ref(model: type[models.Model]) -> str:
    """How erdify names a relation target: the class, qualified outside the source's app.

    A contrib model (``auth.Group``) is never drawn, so erdify keeps its app
    label and a project model with the same class name can't take its edges.
    """
    meta = model._meta
    return (
        meta.object_name if meta.app_label == APP_LABEL else f"{meta.app_label}.{meta.object_name}"
    )


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
        (f.name, _model_ref(f.related_model._meta.concrete_model))
        for f in meta.local_many_to_many
        if f.remote_field.through._meta.auto_created
    )
    return Table(table=table_name(model), columns=columns, m2m=m2m)
