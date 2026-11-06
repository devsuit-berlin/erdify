"""Types and small helpers shared by the parser modules."""

import ast
import re
from typing import Dict, List, Tuple, TypeVar

from ..config import FieldInfo, is_structural_link_table

__all__ = ["MODEL_SOURCES", "is_structural_link_table"]

#: Model frameworks erdify can recognize, in classification order.
MODEL_SOURCES = ("sqlmodel", "sqlalchemy", "django", "dataclass", "pydantic")

_V = TypeVar("_V")

# A relationship while parsing: (target, type, attribute, nullable). The
# public EntityInfo.relationships keeps (target, type, attribute); the flag
# goes to EntityInfo.nullable_relationships.
_Rel = Tuple[str, str, str, bool]

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
