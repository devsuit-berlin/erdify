"""Django app labels, read statically: the prefix of a default table name.

Django names a model's table ``<app_label>_<model name, lower-cased>`` unless
``Meta.db_table`` says otherwise. The app label is resolved in Django's order,
from what the source shows:

1. ``Meta.app_label`` on the model (read by the dialect).
2. The ``AppConfig`` in the app's ``apps.py``, chosen like
   ``AppConfig.create``: configs with ``default = False`` are dropped, then the
   only one left, else the one with ``default = True``. Its ``label``, else the
   last component of its ``name``; attributes are looked up through config
   classes defined in the same file, and the last assignment wins.
3. The name of the app package.

The app package is found by walking up the Python package chain (directories
with an ``__init__.py``) from the model file: the nearest directory with an
``apps.py``; else the parent of the nearest ``models`` package
(``shop/models/billing/invoice.py`` -> ``shop``); else the directory of the
file. The walk never leaves the package chain, so an unrelated ``models``
directory above the project can't be picked up.

A ``Meta.app_label``, also one inherited from an abstract base's ``Meta``
(#279), takes precedence; the dialect reads it before asking this module.

An ``AppConfig`` chosen explicitly in ``INSTALLED_APPS`` (``"shop.apps.Custom"``)
is not known to erdify; the app's default config is used instead.
"""

import ast
from pathlib import Path
from typing import Dict, List

# A class attribute whose last assignment is not a literal: its value is unknown.
_UNKNOWN = object()


def app_package(model_file: Path) -> Path:
    """The app package a model file belongs to (see the module docstring).

    The path is resolved first, so the result doesn't depend on how the input
    path was written (``.``, ``..``).
    """
    chain = _package_chain(model_file.resolve().parent)
    for directory in chain:
        if (directory / "apps.py").is_file():
            return directory
    for directory in chain:
        if directory.name == "models":
            return directory.parent
    return chain[0]


def _package_chain(start: Path) -> List[Path]:
    """``start`` and those of its ancestors that are Python packages.

    The walk stops below the first ancestor without an ``__init__.py``, so a
    directory outside the package (an unrelated ``apps.py`` or ``models``
    directory above the project) is never considered.
    """
    chain = [start]
    directory = start.parent
    while (directory / "__init__.py").is_file() and directory.parent != directory:
        chain.append(directory)
        directory = directory.parent
    return chain


def app_label(package: Path) -> str:
    """The app label of the Django app in ``package``."""
    configs = _app_configs(package / "apps.py")
    config = _default_config(configs)
    if config is not None:
        label = _attr(config, "label", configs)
        if isinstance(label, str) and label:
            return label
        name = _attr(config, "name", configs)
        if isinstance(name, str) and name:
            return name.rpartition(".")[2]
    return package.name


def _app_configs(apps_file: Path) -> Dict[str, ast.ClassDef]:
    """The ``AppConfig`` subclasses defined in ``apps_file``, by name.

    Subclasses of another config in the same file count too.
    """
    try:
        tree = ast.parse(apps_file.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError, RecursionError):
        # ValueError: a null byte on Python 3.11 (3.12+ raises SyntaxError);
        # UnicodeDecodeError is a ValueError too.
        return {}
    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
    configs: Dict[str, ast.ClassDef] = {}
    changed = True
    while changed:  # fixed point over local subclassing, in any order
        changed = False
        for name, node in classes.items():
            if name not in configs and any(
                _base_name(base) == "AppConfig" or _base_name(base) in configs
                for base in node.bases
            ):
                configs[name] = node
                changed = True
    return configs


def _default_config(configs: Dict[str, ast.ClassDef]) -> ast.ClassDef | None:
    """The config Django picks as the app's default, if it can be told from source."""
    candidates = [c for c in configs.values() if _attr(c, "default", configs) is not False]
    if len(candidates) == 1:
        return candidates[0]
    marked = [c for c in candidates if _attr(c, "default", configs) is True]
    return marked[0] if len(marked) == 1 else None


def _base_name(base: ast.expr) -> str:
    if isinstance(base, ast.Attribute):
        return base.attr
    return base.id if isinstance(base, ast.Name) else ""


def _attr(
    node: ast.ClassDef, attr: str, configs: Dict[str, ast.ClassDef], depth: int = 0
) -> object | None:
    """A class attribute's literal value, looked up through same-file bases.

    The last assignment in a class body wins (as in Python). A non-literal last
    assignment makes the value unknown (None), rather than falling back to an
    earlier literal or a base class.
    """
    value = _own_attr(node, attr)
    if value is _UNKNOWN:
        return None
    if value is not None or depth > len(configs):
        return value
    for base in node.bases:
        parent = configs.get(_base_name(base))
        if parent is not None:
            inherited = _attr(parent, attr, configs, depth + 1)
            if inherited is not None:
                return inherited
    return None


def _own_attr(node: ast.ClassDef, attr: str) -> object | None:
    """The last value assigned to ``attr`` in the class body; ``_UNKNOWN`` if not literal."""
    value: object | None = None
    for statement in node.body:
        if isinstance(statement, ast.Assign):
            targets = statement.targets
        elif isinstance(statement, ast.AnnAssign) and statement.value is not None:
            targets = [statement.target]
        else:
            continue
        if any(isinstance(t, ast.Name) and t.id == attr for t in targets):
            assigned = statement.value
            value = assigned.value if isinstance(assigned, ast.Constant) else _UNKNOWN
    return value
