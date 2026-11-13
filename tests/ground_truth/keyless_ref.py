"""Pydantic / dataclass reference loader: build a :class:`Schema` from the classes' own fields.

The source is executed as a fresh module. The fields of a Pydantic model come
from ``Model.model_fields`` (after ``model_rebuild()`` resolves forward
references), those of a dataclass from ``dataclasses.fields()``, each type
resolved in the class that declared the field; both include inherited fields.

Pydantic models and dataclasses describe objects, not tables, so there are no
keys: every column is compared by name and nullability only. A column is
nullable when its type admits ``None`` (``Optional[X]``, ``X | None``,
``Literal[..., None]``), which is what an ERD can show; whether the field has
a default (Pydantic's ``is_required()``) is not part of the schema. A field
whose type names exactly one model of the source, optionally in a collection,
is a relationship instead (erdify's nested-model edges). Type display strings
are erdify's presentation and not compared.
"""

from __future__ import annotations

import ast
import collections.abc
import dataclasses
import enum
import inspect
import sys
import types
import typing
from collections.abc import Iterator
from typing import Annotated, Any, Final, Literal, Union, get_args, get_origin

import pydantic
from pydantic.errors import PydanticUserError

from .schema import Column, Relationship, Schema, Table

# A top-level name: a relative import in a source fails (it is not
# self-contained) instead of reaching into this package.
MODULE = "erdify_ground_truth_keyless"

NoneType = type(None)


class Unloadable(Exception):
    """The source is not a complete model module on its own.

    Raised only for sources that reference names or modules outside
    themselves (``NameError`` / ``ImportError`` / ``SyntaxError``, a forward
    reference Pydantic can't resolve), which erdify handles by design. Any
    other exception propagates and fails the test, so a broken harness can't
    turn comparisons into silent skips.
    """


class Rejected(Unloadable):
    """Pydantic or ``@dataclass`` refuses to create a class at all.

    A ``PydanticUserError`` (e.g. a type Pydantic has no schema for), or the
    ``TypeError`` / ``ValueError`` / ``SyntaxError`` class creation raises (a
    dataclass field without a default after one with a default, a mutable
    default, bases with no consistent MRO, a string annotation that is no
    expression). There is no schema to compare.
    """


def load(source: str) -> Schema:
    """Execute ``source`` as a module and normalise its Pydantic models and dataclasses.

    An entity is a ``BaseModel`` subclass defined in the source, or a class
    the source decorates with ``@dataclass`` (it has its own
    ``__dataclass_fields__``; a plain subclass of a dataclass is not one).
    Table names are left empty: erdify's are its own choice.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise Unloadable(f"SyntaxError: {exc}") from exc
    module = types.ModuleType(MODULE)
    module.__file__ = "<models>"
    # get_type_hints() and Pydantic resolve string annotations in the module
    # of the class, looked up in sys.modules.
    sys.modules[MODULE] = module
    try:
        try:
            exec(compile(tree, "<models>", "exec", dont_inherit=True), module.__dict__)
        except (NameError, ImportError) as exc:
            raise Unloadable(f"{type(exc).__name__}: {exc}") from exc
        except (PydanticUserError, TypeError, ValueError, SyntaxError) as exc:
            # SyntaxError: a string annotation that is no expression ("User |").
            raise Rejected(f"{type(exc).__name__}: {exc}") from exc
        classes = list(_classes(module))
        entities = {cls for cls in classes if _is_model(cls)}
        tables = {cls.__name__: _table(cls, module, entities) for cls in entities}
        enums = {
            cls.__name__: tuple(cls.__members__)
            for cls in classes
            # A base without members (a project's own enum base) has nothing to draw.
            if issubclass(cls, enum.Enum) and cls.__members__
        }
        return Schema(tables=tables, enums=enums)
    finally:
        del sys.modules[MODULE]


def _classes(module: types.ModuleType) -> Iterator[type]:
    """Classes defined in the source, including ones nested in a class body."""
    seen: set[type] = set()
    pending = list(vars(module).values())
    while pending:
        value = pending.pop()
        if isinstance(value, type) and value.__module__ == MODULE and value not in seen:
            seen.add(value)
            yield value
            pending.extend(vars(value).values())


def _is_model(cls: type) -> bool:
    return "__dataclass_fields__" in vars(cls) or issubclass(cls, pydantic.BaseModel)


def _field_types(cls: type, module: types.ModuleType) -> dict[str, Any]:
    """Field name -> type, as the library defines the class's fields."""
    if "__dataclass_fields__" in vars(cls):
        try:
            return {f.name: _dataclass_field_type(cls, f) for f in dataclasses.fields(cls)}
        except NameError as exc:
            raise Unloadable(f"NameError: {exc}") from exc
    model = typing.cast(type[pydantic.BaseModel], cls)
    try:
        # Resolves forward references to models defined later in the source.
        model.model_rebuild(_types_namespace=dict(vars(module)))
    except NameError as exc:  # PydanticUndefinedAnnotation is a NameError
        raise Unloadable(f"{type(exc).__name__}: {exc}") from exc
    return {name: info.annotation for name, info in model.model_fields.items()}


def _dataclass_field_type(cls: type, field: dataclasses.Field[Any]) -> Any:
    """The resolved type of ``field``, from the class that declared it.

    ``field.type`` may be a string; ``get_type_hints(cls)`` resolves it but
    follows Python's attribute lookup, which can pick another base's
    annotation than the one ``dataclasses.fields()`` merged (a diamond).
    """
    owner = next(
        (
            base
            for base in cls.__mro__
            if vars(base).get("__dataclass_fields__", {}).get(field.name) is field
            and field.name in inspect.get_annotations(base)
        ),
        None,
    )
    if owner is None:
        raise AssertionError(f"no class in {cls.__name__}'s MRO declares field {field.name!r}")
    return typing.get_type_hints(owner, include_extras=True)[field.name]


def _table(cls: type, module: types.ModuleType, entities: set[type]) -> Table:
    columns: dict[str, Column] = {}
    relationships: dict[str, Relationship] = {}
    for name, tp in _field_types(cls, module).items():
        ref = _reference(tp, entities)
        if ref is None:
            columns[name] = Column(nullable=_admits_none(tp))
        else:
            target, many, nullable = ref
            relationships[name] = Relationship(
                target=target, kind="many" if many else "one", nullable=nullable and not many
            )
    return Table(table="", columns=columns, relationships=relationships)


def _unwrap(tp: Any) -> Any:
    """The type inside ``Annotated[...]`` and the ``Final[...]`` qualifier."""
    while get_origin(tp) in (Annotated, Final):
        tp = get_args(tp)[0]
    return tp


def _is_union(tp: Any) -> bool:
    return get_origin(tp) in (Union, types.UnionType)


def _is_none(tp: Any) -> bool:
    """``None`` itself, also as ``Annotated[None, ...]``."""
    return _unwrap(tp) in (None, NoneType)


def _admits_none(tp: Any) -> bool:
    """``None`` is a value of ``tp``: ``Optional[X]``, ``X | None``, ``Literal[None]``."""
    tp = _unwrap(tp)
    if tp is None or tp is NoneType:
        return True
    if _is_union(tp):
        return any(_admits_none(arg) for arg in get_args(tp))
    if get_origin(tp) is Literal:
        return None in get_args(tp)
    return False


def _reference(tp: Any, entities: set[type], many: bool = False) -> tuple[str, bool, bool] | None:
    """``(target, many, nullable)`` when ``tp`` names exactly one model of the source.

    A model, optionally ``None``-able, inside ``Annotated``, or the items of a
    collection (a single-argument collection type, ``tuple[X, ...]``, a
    mapping's values). A union of different models, or of a model and another
    type, names no single model.
    """
    tp = _unwrap(tp)
    if isinstance(tp, type) and tp in entities:
        return tp.__name__, many, False
    if _is_union(tp):
        args = get_args(tp)
        rest = [arg for arg in args if not _is_none(arg)]
        refs = [_reference(arg, entities, many) for arg in rest]
        if not refs or any(ref is None for ref in refs):
            return None
        resolved = [ref for ref in refs if ref is not None]
        if len({(target, is_many) for target, is_many, _ in resolved}) != 1:
            return None
        target, is_many, _ = resolved[0]
        return target, is_many, len(rest) < len(args) or any(n for *_, n in resolved)
    origin, args = get_origin(tp), get_args(tp)
    if not isinstance(origin, type):
        return None
    if origin is tuple:
        if len(args) == 2 and args[1] is Ellipsis:
            return _reference(args[0], entities, True)
        return None
    if issubclass(origin, collections.abc.Mapping):
        return _reference(args[1], entities, True) if len(args) == 2 else None
    if issubclass(origin, collections.abc.Iterable) and not issubclass(origin, (str, bytes)):
        return _reference(args[0], entities, True) if len(args) == 1 else None
    return None
