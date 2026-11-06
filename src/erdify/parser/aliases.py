"""Column type aliases, resolved per module like Python names (#241, #249, #250).

SQLAlchemy's ``intpk = Annotated[int, mapped_column(primary_key=True)]``
lets ``id: Mapped[intpk]`` declare a primary key. Which object ``intpk``
names depends on the module it is used in, so it is resolved there: the
module's last module-level binding of the name wins, an import is followed
into the scanned file it names, and an alias built on another one
(``Annotated[intpk, ...]``) resolves that one in its own module.
"""

import ast
from pathlib import Path
from typing import Dict, Iterable, List, NamedTuple, Set, Tuple

from .annotations import defines_column_alias, expand_aliases


class _Binding(NamedTuple):
    """A module-level binding of one name: the last one in the module counts."""

    #: ``"alias"`` (``X = Annotated[...]``), ``"import"`` or ``"other"``.
    kind: str
    #: The alias value (``"alias"``), or ``None``.
    value: ast.expr | None = None
    #: The imported module, as written (``"import"``; ``None`` for ``from . import``).
    module: str | None = None
    #: Leading dots of a relative import (``"import"``).
    level: int = 0
    #: The name imported from that module (``"import"``).
    original: str = ""


class AliasResolver:
    """Resolves column type aliases per scanned module.

    Args:
        trees: Each scanned file's syntax tree.
        classes: Names of the parsed classes; a class shadows a same-named alias.
    """

    def __init__(self, trees: Dict[Path, ast.Module], classes: Iterable[str]):
        self._trees = trees
        self._classes = set(classes)
        self._scopes: Dict[Path, Dict[str, _Binding]] = {}
        self._stars: Dict[Path, List[Tuple[str | None, int]]] = {}
        self._cache: Dict[Path, Dict[str, ast.expr]] = {}
        self._fallback: Dict[str, ast.expr] | None = None

    def aliases_for(self, file: Path | None) -> Dict[str, ast.expr]:
        """Alias name -> fully expanded ``Annotated[...]`` usable in ``file``.

        Besides the names ``file`` binds or star-imports, a name it does not
        bind at all falls back to the alias of that name if exactly one
        scanned module defines it (the import may be invisible, e.g. under
        ``TYPE_CHECKING``).
        """
        if file is None or file not in self._trees:
            return dict(self._fallback_aliases())
        cached = self._cache.get(file)
        if cached is not None:
            return cached
        result: Dict[str, ast.expr] = {}
        bound = set(self._scope(file))
        for name in bound:
            value = self._resolve(file, name, ())
            if value is not None:
                result[name] = value
        for name, value in self._fallback_aliases().items():
            if name in bound or name in result:
                continue
            via_star = self._resolve_star(file, name, ())
            result[name] = via_star if via_star is not None else value
        for module, level in self._stars.get(file, ()):  # star-imported aliases
            target = self._find_module(file, module, level)
            if target is not None:
                for name in self._scope(target):
                    if name not in bound and name not in result:
                        value = self._resolve(target, name, ())
                        if value is not None:
                            result[name] = value
        self._cache[file] = result
        return result

    # -- scope -----------------------------------------------------------------

    def _scope(self, file: Path) -> Dict[str, _Binding]:
        """The module's last binding of each name bound at module level."""
        scope = self._scopes.get(file)
        if scope is not None:
            return scope
        scope = {}
        stars: List[Tuple[str | None, int]] = []
        for node in self._trees[file].body:
            if isinstance(node, ast.Assign):
                if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                    scope[node.targets[0].id] = self._assigned(node.value)
                else:  # chained or unpacking: whatever it binds is not an alias
                    for target in node.targets:
                        for sub in ast.walk(target):
                            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                                scope[sub.id] = _Binding("other")
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                scope[node.target.id] = self._assigned(node.value)
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == "*":
                        stars.append((node.module, node.level))
                    else:
                        scope[alias.asname or alias.name] = _Binding(
                            "import", module=node.module, level=node.level, original=alias.name
                        )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    scope[alias.asname or alias.name.split(".")[0]] = _Binding("other")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                scope[node.name] = _Binding("other")
            elif type(node).__name__ == "TypeAlias":
                # PEP 695 `type X = ...`: SQLAlchemy takes no mapped_column() from it.
                alias_name = getattr(node, "name", None)
                if isinstance(alias_name, ast.Name):
                    scope[alias_name.id] = _Binding("other")
        self._scopes[file] = scope
        self._stars[file] = stars
        return scope

    @staticmethod
    def _assigned(value: ast.expr | None) -> _Binding:
        if isinstance(value, ast.Subscript):
            return _Binding("alias", value=value)
        return _Binding("other")

    # -- resolution --------------------------------------------------------------

    def _resolve(
        self, file: Path, name: str, stack: Tuple[Tuple[Path, str], ...]
    ) -> ast.expr | None:
        """The expanded column alias ``name`` refers to in ``file``, or None."""
        if name in self._classes or (file, name) in stack:
            return None
        binding = self._scope(file).get(name)
        if binding is None:
            return self._resolve_star(file, name, stack)
        stack = stack + ((file, name),)
        if binding.kind == "import":
            target = self._find_module(file, binding.module, binding.level)
            return self._resolve(target, binding.original, stack) if target else None
        if binding.kind != "alias" or binding.value is None:
            return None
        # An alias built on other aliases resolves them in its own module (#249).
        local: Dict[str, ast.expr] = {}
        for sub in ast.walk(binding.value):
            if isinstance(sub, ast.Name) and sub.id not in local:
                inner = self._resolve(file, sub.id, stack)
                if inner is not None:
                    local[sub.id] = inner
        expanded = expand_aliases(binding.value, local)
        return expanded if defines_column_alias(expanded) else None

    def _resolve_star(
        self, file: Path, name: str, stack: Tuple[Tuple[Path, str], ...]
    ) -> ast.expr | None:
        self._scope(file)
        for module, level in self._stars.get(file, ()):
            target = self._find_module(file, module, level)
            if target is not None and name in self._scope(target):
                return self._resolve(target, name, stack)
        return None

    def _find_module(self, file: Path, module: str | None, level: int) -> Path | None:
        """The scanned file an import refers to, if any."""
        parts = module.split(".") if module else []
        if level:
            base = file.parent
            for _ in range(level - 1):
                base = base.parent
            stem = base.joinpath(*parts) if parts else base
            for candidate in (stem.with_suffix(".py"), stem / "__init__.py"):
                if candidate in self._trees:
                    return candidate
            return None
        matches = [
            path
            for path in self._trees
            if path.with_suffix("").parts[-len(parts) :] == tuple(parts)
            or (path.name == "__init__.py" and path.parent.parts[-len(parts) :] == tuple(parts))
        ]
        return matches[0] if len(matches) == 1 else None

    def _fallback_aliases(self) -> Dict[str, ast.expr]:
        """Aliases defined (not imported) in exactly one scanned module, by name."""
        if self._fallback is not None:
            return self._fallback
        found: Dict[str, List[ast.expr]] = {}
        for file in self._trees:
            for name, binding in self._scope(file).items():
                if binding.kind == "alias":
                    value = self._resolve(file, name, ())
                    if value is not None:
                        found.setdefault(name, []).append(value)
        unique: Set[str] = {
            name for name, values in found.items() if len({ast.dump(v) for v in values}) == 1
        }
        self._fallback = {name: found[name][0] for name in unique}
        return self._fallback
