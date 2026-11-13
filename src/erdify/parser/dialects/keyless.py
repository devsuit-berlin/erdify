"""Keyless sources: Pydantic models and dataclasses.

They describe objects, not tables: no keys unless ``--infer-keys``, and a
field typed as another model is a relationship.
"""

import ast
from dataclasses import replace
from typing import Dict, List, Tuple

from ...config import FieldInfo
from ..common import _ClassMembers, _Rel
from ..inheritance import merge_members
from .annotated import AnnotatedDialect
from .base import ParseContext


class _FieldMergeDialect(AnnotatedDialect):
    """A keyless dialect whose classes merge inherited fields like ``dataclasses.fields()``.

    A model class (:meth:`owns_fields`) merges each base's fields in reversed
    MRO, then its own annotations. So in ``Child(Left, Middle)`` an attribute
    ``Left`` merely inherits still overrides one ``Middle`` redeclares, unlike
    Python's attribute lookup. A plain class has no fields of its own: it
    exposes those of the first model class in its MRO. ``mixin_fields``: the
    annotations of plain classes in the hierarchy also become fields, where no
    model class declares the attribute (the first such class in the MRO wins).
    """

    #: Whether a plain (non-model) base's annotations become fields.
    mixin_fields: bool = False

    def __init__(self, ctx: ParseContext):
        super().__init__(ctx)
        self._fields_cache: Dict[str, Tuple[Dict[str, FieldInfo], Dict[str, _Rel]]] = {}

    def owns_fields(self, class_node: ast.ClassDef) -> bool:
        """Whether the class is a model class with fields of its own."""
        return self.detect(class_node)

    def merge(
        self,
        class_node: ast.ClassDef,
        merge_order: List[str],
        members: Dict[str, _ClassMembers],
    ) -> Tuple[Dict[str, FieldInfo], Dict[str, _Rel]]:
        if self.classes.mro(class_node.name) is None:
            return super().merge(class_node, merge_order, members)
        fields, rels = self._effective_fields(class_node.name, members)
        # The cache is shared across entities, and building an entity mutates
        # fields (e.g. is_unique), so each entity gets its own copies.
        return {attr: replace(f) for attr, f in fields.items()}, dict(rels)

    def _effective_fields(
        self, name: str, members: Dict[str, _ClassMembers]
    ) -> Tuple[Dict[str, FieldInfo], Dict[str, _Rel]]:
        """A class's fields as the framework computes them; cached per parse.

        A class's own members do not depend on the entity being built.
        """
        memo = self._fields_cache
        if name in memo:
            return memo[name]
        mro = self.classes.mro(name) or [name]
        if not self.owns_fields(self.classes.all[name]):
            owner = next((c for c in mro if self.owns_fields(self.classes.all[c])), None)
            result = self._effective_fields(owner, members) if owner is not None else ({}, {})
            memo[name] = result
            return result
        synthetic: Dict[str, _ClassMembers] = {}
        for base in mro[:0:-1]:
            base_fields, base_rels = self._effective_fields(base, members)
            synthetic[base] = (base_fields, base_rels, [*base_fields, *base_rels])
        synthetic[name] = members[name]
        fields, rels = merge_members([*mro[:0:-1], name], synthetic, self)
        if self.mixin_fields:
            fields, rels = dict(fields), dict(rels)
            for base in mro:
                if self.owns_fields(self.classes.all[base]):
                    continue
                base_fields, base_rels, _ = members[base]
                for attr, field in base_fields.items():
                    if attr not in fields and attr not in rels:
                        fields[attr] = field
                for attr, rel in base_rels.items():
                    if attr not in fields and attr not in rels:
                        rels[attr] = rel
        memo[name] = (fields, rels)
        return fields, rels


class DataclassDialect(_FieldMergeDialect):
    """A class decorated with ``@dataclass`` (bare or called).

    Its members merge like ``dataclasses.fields()``: an undecorated base adds
    no fields, not even annotations of its own.
    """

    kind = "dataclass"
    keyless = True

    def detect(self, class_node: ast.ClassDef) -> bool:
        return self._is_dataclass(class_node)

    @staticmethod
    def _is_dataclass(class_node: ast.ClassDef) -> bool:
        """Check if a class is decorated with @dataclass (bare or called)."""
        for dec in class_node.decorator_list:
            if isinstance(dec, ast.Name) and dec.id == "dataclass":
                return True
            if isinstance(dec, ast.Attribute) and dec.attr == "dataclass":
                return True
            if isinstance(dec, ast.Call):
                func = dec.func
                if isinstance(func, ast.Name) and func.id == "dataclass":
                    return True
                if isinstance(func, ast.Attribute) and func.attr == "dataclass":
                    return True
        return False


class PydanticDialect(_FieldMergeDialect):
    """A ``BaseModel`` subclass (directly or transitively), or of ``ctx.base_classes``.

    Pydantic builds ``model_fields`` from the bases' ``model_fields`` like
    ``dataclasses.fields()`` merges, and a plain mixin's annotations become
    fields too.
    """

    kind = "pydantic"
    keyless = True
    mixin_fields = True

    def detect(self, class_node: ast.ClassDef) -> bool:
        return self._inherits_basemodel(class_node)

    def skip_reason(self, class_node: ast.ClassDef) -> str | None:
        """Skip a ninja-style ``ModelSchema``, whose fields come from a Django model."""
        derived = model_derived_schema(class_node)
        if derived is None:
            return None
        holder, target = derived
        return (
            f"Warning: skipped {class_node.name} - its fields come from "
            f"{holder}.model ({target}), which erdify does not resolve. "
            "Drawing it would add an entity with no fields. "
            "See https://github.com/devsuit-berlin/erdify/issues/171"
        )

    def _inherits_basemodel(
        self, class_node: ast.ClassDef, visited: set[str] | None = None
    ) -> bool:
        """Check if a class inherits from Pydantic's BaseModel, directly or via ancestors.

        Any name in ``ctx.base_classes`` counts as well, which is how a base
        defined outside the scanned files (``ninja.Schema``, a shared internal
        ``BaseSchema``) can be recognised at all.
        """
        visited = visited if visited is not None else set()
        if class_node.name in visited:
            return False
        visited.add(class_node.name)

        for base in class_node.bases:
            if isinstance(base, ast.Name):
                if base.id == "BaseModel" or base.id in self.ctx.base_classes:
                    return True
                ancestor = self.classes.all.get(base.id)
                if ancestor is not None and self._inherits_basemodel(ancestor, visited):
                    return True
            elif isinstance(base, ast.Attribute):
                if base.attr == "BaseModel" or base.attr in self.ctx.base_classes:
                    return True
        return False


def model_derived_schema(class_node: ast.ClassDef) -> Tuple[str, str] | None:
    """Detect a ninja-style ``ModelSchema`` and report where its fields come from.

    django-ninja's ``ModelSchema`` (inner ``Meta``) and ninja-schema's
    (inner ``Config``) take their fields from a Django model named in that
    inner class rather than from the class body. erdify cannot resolve the
    reference, so the entity would be drawn with no fields at all — worse
    than not drawing it. Detection is deliberately narrow: only an inner
    ``Meta``/``Config`` that assigns ``model`` counts, so an ordinary
    Pydantic model with a nested config class is untouched.

    Returns:
        ``(holder, target)`` where *holder* is ``"Meta"`` or ``"Config"``
        and *target* is the referenced model's name, or ``None`` when the
        class is not a model-derived schema.
    """
    for node in class_node.body:
        if not isinstance(node, ast.ClassDef) or node.name not in ("Meta", "Config"):
            continue
        for inner in node.body:
            if not isinstance(inner, ast.Assign):
                continue
            for target in inner.targets:
                if not (isinstance(target, ast.Name) and target.id == "model"):
                    continue
                value = inner.value
                if isinstance(value, ast.Name):
                    return node.name, value.id
                if isinstance(value, ast.Attribute):
                    return node.name, value.attr
                if isinstance(value, ast.Call):
                    return node.name, "unresolved"
                return node.name, "unresolved"
    return None
