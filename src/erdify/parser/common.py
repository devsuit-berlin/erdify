"""Types and small helpers shared by the parser modules."""

import ast
import re
from typing import Dict, List, NamedTuple, Tuple, TypeVar

from ..config import FieldInfo

_V = TypeVar("_V")


class _Rel(NamedTuple):
    """A relationship while parsing.

    The public ``EntityInfo.relationships`` keeps ``(target, kind, attr)``;
    ``nullable`` goes to ``EntityInfo.nullable_relationships`` and
    ``inverse`` to ``EntityInfo.inverse_relationships``.
    """

    target: str
    kind: str
    attr: str
    nullable: bool
    #: The other side's attribute, when named explicitly (``back_populates=``).
    inverse: str | None = None


# A class body's (fields, relationships, declared attribute names).
_ClassMembers = Tuple[Dict[str, FieldInfo], Dict[str, _Rel], List[str]]

#: Enum base class names recognized by erdify (stdlib Enum + Django choices).
ENUM_BASES = frozenset({"Enum", "TextChoices", "IntegerChoices"})


def is_enum_class(class_node: ast.ClassDef) -> bool:
    """Check if a class is an Enum or a Django TextChoices/IntegerChoices."""
    for base in class_node.bases:
        if isinstance(base, ast.Attribute) and base.attr in ENUM_BASES:
            return True
        if isinstance(base, ast.Name) and base.id in ENUM_BASES:
            return True
    return False


def to_snake_case(name: str) -> str:
    """Convert CamelCase to snake_case."""
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()
