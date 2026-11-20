"""The multi-module source helpers of the ground-truth harness (#380)."""

from __future__ import annotations

import sys
from pathlib import Path

from tests.ground_truth.packages import entity_keys, importable, module_names


def _tree(root: Path) -> None:
    for rel, text in {
        "pkg/__init__.py": "",
        "pkg/models.py": "class Address:\n    pass\n",
        "pkg/sub/__init__.py": "",
        "pkg/sub/models.py": "class Address:\n    pass\n",
        "loose/models.py": "X = 1\n",  # no __init__.py: not a package
    }.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def test_module_names_are_the_importable_modules(tmp_path: Path) -> None:
    _tree(tmp_path)

    assert module_names(tmp_path) == ["pkg", "pkg.models", "pkg.sub", "pkg.sub.models"]


def test_importable_imports_fresh_and_cleans_up(tmp_path: Path) -> None:
    _tree(tmp_path)
    before = list(sys.path)

    with importable(tmp_path) as names:
        import importlib

        modules = [importlib.import_module(name) for name in names]
        assert modules[1].__name__ == "pkg.models"

    assert sys.path == before
    assert not any(name == "pkg" or name.startswith("pkg.") for name in sys.modules)


def test_entity_keys_qualify_shared_names() -> None:
    a = type("Address", (), {"__module__": "billing.models"})
    b = type("Address", (), {"__module__": "shipping.models"})
    c = type("Order", (), {"__module__": "orders.models"})

    assert entity_keys([a, b, c]) == {
        a: "billing.models.Address",
        b: "shipping.models.Address",
        c: "Order",
    }
