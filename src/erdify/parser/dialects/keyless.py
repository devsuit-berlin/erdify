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


class DataclassDialect(AnnotatedDialect):
    """A class decorated with ``@dataclass`` (bare or called).

    Its members merge like ``dataclasses.fields()`` (:meth:`_dataclass_fields`).
    """

    kind = "dataclass"
    model_references = True

    def __init__(self, ctx: ParseContext):
        super().__init__(ctx)
        self._dataclass_cache: Dict[str, Tuple[Dict[str, FieldInfo], Dict[str, _Rel]]] = {}

    def detect(self, class_node: ast.ClassDef) -> bool:
        return self._is_dataclass(class_node)

    def merge(
        self,
        class_node: ast.ClassDef,
        merge_order: List[str],
        members: Dict[str, _ClassMembers],
    ) -> Tuple[Dict[str, FieldInfo], Dict[str, _Rel]]:
        if self.classes.mro(class_node.name) is not None:
            return self._dataclass_fields(class_node.name, members)
        return super().merge(class_node, merge_order, members)

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

    def _dataclass_fields(
        self, name: str, members: Dict[str, _ClassMembers]
    ) -> Tuple[Dict[str, FieldInfo], Dict[str, _Rel]]:
        """The members of a dataclass entity: ``dataclasses.fields()`` plus mixins.

        First the stdlib result (:meth:`_effective_dataclass_fields`). Then
        annotations of undecorated mixins in the hierarchy, which the stdlib
        ignores but erdify has always shown, fill in only attributes no
        dataclass declares (the first such mixin in the MRO wins).
        """
        fields, rels = self._effective_dataclass_fields(name, members)
        # The cache is shared across entities, and building an entity mutates
        # fields (e.g. is_unique), so each entity gets its own copies.
        fields, rels = {attr: replace(f) for attr, f in fields.items()}, dict(rels)
        for base in self.classes.mro(name) or [name]:
            if self._is_dataclass(self.classes.all[base]):
                continue
            base_fields, base_rels, _ = members[base]
            for attr, field in base_fields.items():
                if attr not in fields and attr not in rels:
                    fields[attr] = replace(field)
            for attr, rel in base_rels.items():
                if attr not in fields and attr not in rels:
                    rels[attr] = rel
        return fields, rels

    def _effective_dataclass_fields(
        self, name: str, members: Dict[str, _ClassMembers]
    ) -> Tuple[Dict[str, FieldInfo], Dict[str, _Rel]]:
        """A class's ``__dataclass_fields__``, as the stdlib computes it.

        A decorated class merges each base's ``__dataclass_fields__`` in
        reversed MRO, then its own annotations. So in ``Child(Left, Middle)``
        an attribute ``Left`` merely inherits still overrides one ``Middle``
        redeclares. An undecorated class has no fields of its own: it exposes
        those of the first decorated class in its MRO. Cached per parse; a
        class's own members do not depend on the entity being built.
        """
        memo = self._dataclass_cache
        if name in memo:
            return memo[name]
        mro = self.classes.mro(name) or [name]
        if not self._is_dataclass(self.classes.all[name]):
            owner = next((c for c in mro if self._is_dataclass(self.classes.all[c])), None)
            result = (
                self._effective_dataclass_fields(owner, members) if owner is not None else ({}, {})
            )
            memo[name] = result
            return result
        synthetic: Dict[str, _ClassMembers] = {}
        for base in mro[:0:-1]:
            base_fields, base_rels = self._effective_dataclass_fields(base, members)
            synthetic[base] = (base_fields, base_rels, [*base_fields, *base_rels])
        synthetic[name] = members[name]
        result = merge_members([*mro[:0:-1], name], synthetic, "dataclass")
        memo[name] = result
        return result


class PydanticDialect(AnnotatedDialect):
    """A ``BaseModel`` subclass (directly or transitively), or of ``ctx.base_classes``."""

    kind = "pydantic"
    model_references = True

    def detect(self, class_node: ast.ClassDef) -> bool:
        return self._inherits_basemodel(class_node)

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
