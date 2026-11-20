"""Types and small helpers shared by the parser modules."""

import ast
import re
from pathlib import Path
from typing import Dict, List, Mapping, NamedTuple, Set, Tuple, TypeVar

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

#: Enum base class names recognized by erdify: the stdlib ``enum`` bases and
#: Django's choices (#296).
ENUM_BASES = frozenset(
    {"Enum", "IntEnum", "StrEnum", "Flag", "IntFlag", "TextChoices", "IntegerChoices"}
)


def is_enum_class(
    class_node: ast.ClassDef, classes: Mapping[str, ast.ClassDef] | None = None
) -> bool:
    """Check if a class is an enum: based on one of ``ENUM_BASES``, directly or
    through scanned classes in ``classes`` (a project's own enum base, #296)."""
    seen: Set[int] = set()
    pending = [class_node]
    while pending:
        node = pending.pop()
        if id(node) in seen:
            continue
        seen.add(id(node))
        for base in node.bases:
            if isinstance(base, ast.Attribute):
                if isinstance(base.value, ast.Name) and base.value.id == "enum":
                    if base.attr in ENUM_BASES:
                        return True
                name = base.attr  # models.Flag: a scanned model, or Django's choices
            elif isinstance(base, ast.Name):
                name = base.id
            else:
                continue
            # A scanned class of that name (a model called `Flag`) is
            # followed, not taken for the enum base it shares a name with.
            scanned = classes.get(name) if classes is not None else None
            if scanned is not None and scanned is not node:
                pending.append(scanned)
            elif name in ENUM_BASES:
                return True
    return False


def to_snake_case(name: str) -> str:
    """Convert CamelCase to snake_case."""
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def module_name(path: Path) -> str:
    """The dotted module a Python file is, named from its package.

    The package is every directory above the file with an ``__init__.py``,
    as Python imports it with the directory above the top package on
    ``sys.path``: ``src/shop/models/order.py`` (with ``shop/__init__.py`` and
    ``shop/models/__init__.py``) is ``shop.models.order``, a package's
    ``__init__.py`` is the package itself, and a file outside a package is
    its stem. The path is resolved first, so the name doesn't depend on how
    the input path was written.
    """
    path = path.resolve()
    parts = [] if path.name == "__init__.py" else [path.stem]
    directory = path.parent
    if path.name == "__init__.py":
        parts.append(directory.name)
        directory = directory.parent
    while (directory / "__init__.py").is_file() and directory.parent != directory:
        parts.append(directory.name)
        directory = directory.parent
    return ".".join(reversed(parts))


#: The suffix :mod:`erdify.parser.namespaces` gives a colliding class's name.
_INTERNAL_SUFFIX = re.compile(r"__erdify\d+$")


def original_class_name(name: str) -> str:
    """A class's name as written: without the suffix a same-name class gets (#367)."""
    return _INTERNAL_SUFFIX.sub("", name)


def is_module_file(path: Path, importer: Path, source: Tuple[int, str]) -> bool:
    """Whether ``path`` is the module ``source`` (``(level, module)``) names from ``importer``."""
    level, module = source
    parts = [part for part in module.split(".") if part]
    stem = path.with_suffix("")
    own = list(stem.parent.parts) if path.name == "__init__.py" else list(stem.parts)
    if level == 0:
        return bool(parts) and own[-len(parts) :] == parts
    package = importer.parent
    for _ in range(level - 1):
        package = package.parent
    return own == list(package.joinpath(*parts).parts)
