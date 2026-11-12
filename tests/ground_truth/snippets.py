"""Discover the inline model sources that the test suite feeds to erdify.

Many regression tests write a model module from a string literal. Collecting
those literals from the test files (instead of copying them into fixtures)
means every snippet a test adds is checked against the real framework too.
"""

from __future__ import annotations

import ast
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent.parent
DJANGO_HEADER = "from django.db import models\n\n\n"
# A literal is a model source only if it mentions a model base: Model itself,
# or Django's abstract user bases (a user model needs no models.Model).
MODEL_WORDS = ("Model", "AbstractUser", "AbstractBaseUser")


@dataclass(frozen=True)
class Snippet:
    """A model source found in a test file.

    ``id`` is ``<file>::<qualified name>``: the enclosing class / function, or
    the module-level constant the literal is assigned to, plus ``[n]`` when one
    scope holds several snippets. It survives edits elsewhere in the file,
    unlike a line number; the ``[n]`` suffix does depend on the order of the
    literals within that scope.
    """

    id: str
    line: int
    source: str


def django_snippets() -> list[Snippet]:
    """String literals in ``tests/test_*.py`` that define Django models.

    A literal counts when it contains a ``class``, a model base
    (:data:`MODEL_WORDS`), and
    either ``models.Model`` or a ``from django`` import (so an ``apps.py`` with
    only an ``AppConfig`` is not a model source). One without any ``django``
    import (a body that a test helper prefixes with it, e.g. in
    ``test_django_mti.py``) gets the import prepended.
    """
    found: list[Snippet] = []
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        seen: Counter[str] = Counter()
        for scope, node in _literals(tree, ()):
            text = node.value
            if "class " not in text or not any(word in text for word in MODEL_WORDS):
                continue  # e.g. an apps.py with only an AppConfig
            if not ("models.Model" in text or "from django" in text):
                continue
            if "from django" not in text:
                text = DJANGO_HEADER + text
            name = f"{path.name}::{'.'.join(scope) or '<module>'}"
            seen[name] += 1
            found.append(
                Snippet(name if seen[name] == 1 else f"{name}[{seen[name]}]", node.lineno, text)
            )
    return found


#: Words that mark a literal as a SQLAlchemy / SQLModel model source.
SQLALCHEMY_WORDS = (
    "from sqlalchemy",
    "import sqlalchemy",
    "from sqlmodel",
    "import sqlmodel",
    "DeclarativeBase",
    "table=True",
    "__tablename__",
    "Mapped[",
)
SQLALCHEMY_IMPORTS = SQLALCHEMY_WORDS[:4]


def sqlalchemy_snippets(headers: dict[str, str]) -> list[Snippet]:
    """Sources in ``tests/test_*.py`` that define SQLAlchemy or SQLModel models.

    A source is a string literal, or a concatenation (``HEADER + \"\"\"...\"\"\"``)
    of literals and module-level string constants, folded into one source the
    way the test builds it. It counts when it contains a ``class`` or a Core
    ``Table(`` (drawn on its own, #305) and one of :data:`SQLALCHEMY_WORDS`,
    and no Django import (Django sources are :func:`django_snippets`). A
    source without a SQLAlchemy / SQLModel import is a body that a test helper
    prefixes: it gets the module-level constant that ``headers`` names for its
    file prepended (``{"test_x.py": "HEADER"}``),
    and stays as it is in a file without one.
    """
    found: list[Snippet] = []
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        constants = _string_constants(tree)
        header = constants.get(headers.get(path.name, ""), "")
        seen: Counter[str] = Counter()
        for scope, line, text in _sources(tree, (), constants):
            if "class " not in text and "Table(" not in text:
                continue
            if not any(word in text for word in SQLALCHEMY_WORDS):
                continue
            if "from django" in text or "import django" in text:
                continue
            if not any(word in text for word in SQLALCHEMY_IMPORTS):
                text = header + text
            name = f"{path.name}::{'.'.join(scope) or '<module>'}"
            seen[name] += 1
            found.append(Snippet(name if seen[name] == 1 else f"{name}[{seen[name]}]", line, text))
    return found


def _string_constants(tree: ast.Module) -> dict[str, str]:
    """Module-level names bound to a string (also a folded concatenation), last binding wins."""
    constants: dict[str, str] = {}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            value = _fold(node.value, constants)
            if value is not None:
                constants[node.targets[0].id] = value
            else:
                constants.pop(node.targets[0].id, None)
    return constants


def _fold(node: ast.expr, constants: dict[str, str]) -> str | None:
    """The string ``node`` evaluates to, if it is literals and constants joined with ``+``."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return constants.get(f"{node.value.id}.{node.attr}")  # self.X / cls.X
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _fold(node.left, constants), _fold(node.right, constants)
        if left is not None and right is not None:
            return left + right
    return None


def _sources(
    node: ast.AST, scope: tuple[str, ...], constants: dict[str, str]
) -> Iterator[tuple[tuple[str, ...], int, str]]:
    """Like :func:`_literals`, but a foldable concatenation is one source.

    A concatenation that can't be folded (it involves a parameter or a call)
    yields its literal parts on their own.
    """
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.JoinedStr):
            continue
        if (
            isinstance(child, ast.Expr)
            and isinstance(child.value, ast.Constant)
            and isinstance(child.value.value, str)
        ):
            continue  # docstrings
        if isinstance(child, ast.ClassDef):
            # A test class's string constants are reachable as self.X / cls.X.
            members = _string_constants(ast.Module(body=child.body, type_ignores=[]))
            inner = constants | {
                f"{owner}.{name}": value
                for name, value in members.items()
                for owner in ("self", "cls")
            }
            yield from _sources(child, (*scope, child.name), inner)
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield from _sources(child, (*scope, child.name), constants)
        elif (
            isinstance(child, ast.Assign)
            and len(child.targets) == 1
            and isinstance(child.targets[0], ast.Name)
        ):
            yield from _sources(child, (*scope, child.targets[0].id), constants)
        elif isinstance(child, ast.BinOp) and isinstance(child.op, ast.Add):
            text = _fold(child, constants)
            if text is None:
                yield from _sources(child, scope, constants)
            else:
                yield scope, child.lineno, text
        elif isinstance(child, ast.Constant) and isinstance(child.value, str):
            yield scope, child.lineno, child.value
        else:
            yield from _sources(child, scope, constants)


def _literals(
    node: ast.AST, scope: tuple[str, ...]
) -> Iterator[tuple[tuple[str, ...], ast.Constant]]:
    """Yield every string constant below ``node`` with its enclosing scope."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.JoinedStr):
            continue  # an f-string's literal parts are not sources on their own
        if (
            isinstance(child, ast.Expr)
            and isinstance(child.value, ast.Constant)
            and isinstance(child.value.value, str)
        ):
            continue  # docstrings (and other bare string statements) are prose
        if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            yield from _literals(child, (*scope, child.name))
        elif (
            isinstance(child, ast.Assign)
            and len(child.targets) == 1
            and isinstance(child.targets[0], ast.Name)
        ):
            yield from _literals(child, (*scope, child.targets[0].id))
        elif isinstance(child, ast.Constant) and isinstance(child.value, str):
            yield scope, child
        else:
            yield from _literals(child, scope)


def sql_snippets() -> list[Snippet]:
    """Sources in ``tests/test_*.py`` that are SQL DDL with at least one table.

    A source (a literal, or a folded ``+`` concatenation as in
    :func:`sqlalchemy_snippets`) counts when it contains ``CREATE TABLE`` (any
    case).
    """
    found: list[Snippet] = []
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        seen: Counter[str] = Counter()
        for scope, line, text in _sources(tree, (), _string_constants(tree)):
            if "create table" not in text.lower():
                continue
            name = f"{path.name}::{'.'.join(scope) or '<module>'}"
            seen[name] += 1
            found.append(Snippet(name if seen[name] == 1 else f"{name}[{seen[name]}]", line, text))
    return found
