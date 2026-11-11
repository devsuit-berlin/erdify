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

    A literal counts when it contains a ``class`` and either ``models.Model``
    or a ``from django`` import. One without any ``django`` import (a body that a test helper
    prefixes with it, e.g. in ``test_django_mti.py``) gets the import prepended.
    """
    found: list[Snippet] = []
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        seen: Counter[str] = Counter()
        for scope, node in _literals(tree, ()):
            text = node.value
            if "class " not in text or not ("models.Model" in text or "from django" in text):
                continue
            if "from django" not in text:
                text = DJANGO_HEADER + text
            name = f"{path.name}::{'.'.join(scope) or '<module>'}"
            seen[name] += 1
            found.append(
                Snippet(name if seen[name] == 1 else f"{name}[{seen[name]}]", node.lineno, text)
            )
    return found


def _literals(
    node: ast.AST, scope: tuple[str, ...]
) -> Iterator[tuple[tuple[str, ...], ast.Constant]]:
    """Yield every string constant below ``node`` with its enclosing scope."""
    for child in ast.iter_child_nodes(node):
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
