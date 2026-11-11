"""Django app labels, read statically: the prefix of a default table name.

Django names a model's table ``<app_label>_<model name, lower-cased>`` unless
``Meta.db_table`` says otherwise. The app label is resolved in Django's order,
from what the source shows:

1. ``Meta.app_label`` on the model (read by the dialect).
2. The ``AppConfig`` in the app's ``apps.py``: a literal ``label``, else the
   last component of a literal ``name``. With several configs, the one marked
   ``default = True``.
3. The name of the app package: the directory holding ``models.py``, or the
   parent of a ``models/`` package.

An ``AppConfig`` chosen explicitly in ``INSTALLED_APPS`` (``"shop.apps.Custom"``)
is not known to erdify; the app's default config is used instead.
"""

import ast
from pathlib import Path


def app_package(model_file: Path) -> Path:
    """The app package a model file belongs to."""
    package = model_file.parent
    if package.name == "models" and model_file.name != "models.py":
        return package.parent
    return package


def app_label(package: Path) -> str:
    """The app label of the Django app in ``package``."""
    config = _default_config(package / "apps.py")
    if config is not None:
        label = _literal(config, "label")
        if isinstance(label, str) and label:
            return label
        name = _literal(config, "name")
        if isinstance(name, str) and name:
            return name.rpartition(".")[2]
    return package.name


def _default_config(apps_file: Path) -> ast.ClassDef | None:
    """The AppConfig class Django would pick as the app's default, if readable."""
    try:
        tree = ast.parse(apps_file.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None
    configs = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and any(_is_app_config(base) for base in node.bases)
    ]
    if len(configs) == 1:
        return configs[0]
    marked = [c for c in configs if _literal(c, "default") is True]
    return marked[0] if len(marked) == 1 else None


def _is_app_config(base: ast.expr) -> bool:
    name = base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", "")
    return name == "AppConfig"


def _literal(class_node: ast.ClassDef, attr: str) -> object | None:
    """A constant class attribute (``label = "shop"``), or None."""
    for node in class_node.body:
        targets = (
            node.targets
            if isinstance(node, ast.Assign)
            else [node.target]
            if isinstance(node, ast.AnnAssign)
            else []
        )
        value = getattr(node, "value", None)
        if isinstance(value, ast.Constant) and any(
            isinstance(t, ast.Name) and t.id == attr for t in targets
        ):
            return value.value
    return None
