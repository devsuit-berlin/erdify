"""Multi-module sources for the reference loaders (#380).

A source spread over several modules or apps (same-name classes in two
packages, #367) is a directory of packages. :func:`importable` puts it on
``sys.path`` for the time a loader imports it, and :func:`entity_keys` keys
its entities the way erdify names them: the class name, or ``module.Class``
for a name more than one of them has.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from collections import Counter
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path


def module_names(root: Path) -> list[str]:
    """The dotted names of the modules under ``root`` (a package's ``__init__`` is the package).

    Only files in packages (directories with an ``__init__.py``) count, as
    Python imports them; the order is stable.
    """
    names: list[str] = []
    for path in sorted(root.rglob("*.py")):
        parts = list(path.relative_to(root).with_suffix("").parts)
        packages = [root.joinpath(*parts[:i]) for i in range(1, len(parts))]
        if not all((p / "__init__.py").is_file() for p in packages):
            continue
        if parts[-1] == "__init__":
            parts.pop()
        if parts:
            names.append(".".join(parts))
    return names


@contextmanager
def importable(root: Path) -> Iterator[list[str]]:
    """Make the packages under ``root`` importable; yield their module names.

    A package named like a module Python can already import is refused (it
    would shadow it). The source's modules are removed again afterwards, so
    every load imports a fresh copy.
    """
    names = module_names(root)
    tops = {name.split(".")[0] for name in names}
    for top in sorted(tops):
        # A catalog package named like an installed or stdlib module would
        # shadow it while the source is imported: name it differently.
        if top in sys.builtin_module_names or importlib.util.find_spec(top) is not None:
            raise AssertionError(f"{root}: package {top!r} shadows an importable module")

    def ours(module: str) -> bool:
        return module.split(".")[0] in tops

    sys.path.insert(0, str(root))
    importlib.invalidate_caches()
    try:
        yield names
    finally:
        sys.path.remove(str(root))
        for name in [name for name in sys.modules if ours(name)]:
            del sys.modules[name]
        importlib.invalidate_caches()


def enum_keys(classes: Iterable[type]) -> dict[str, type]:
    """Enums by class name; two of the same name are an error.

    erdify draws same-name enum classes as one (see "Same-name enum classes
    in different modules" in ``docs/frameworks/limitations.md``), so a source
    with two would compare by chance. This applies to any source, enums
    nested in two models included; pass only the enums that are drawn.
    """
    found: dict[str, type] = {}
    for cls in classes:
        if cls.__name__ in found and found[cls.__name__] is not cls:
            raise AssertionError(
                f"two enums called {cls.__name__} ({found[cls.__name__].__module__}, "
                f"{cls.__module__}): erdify draws same-name enums as one (limitations.md)"
            )
        found[cls.__name__] = cls
    return found


def entity_keys(classes: Iterable[type]) -> dict[type, str]:
    """Each entity class's key: its name, ``module.Class`` when the name is shared."""
    classes = list(classes)
    counts = Counter(cls.__name__ for cls in classes)
    return {
        cls: cls.__name__ if counts[cls.__name__] == 1 else f"{cls.__module__}.{cls.__name__}"
        for cls in classes
    }
