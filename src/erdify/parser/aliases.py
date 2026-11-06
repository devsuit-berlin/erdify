"""Column type aliases, resolved per module like Python names (#241, #249, #250).

SQLAlchemy's ``intpk = Annotated[int, mapped_column(primary_key=True)]``
lets ``id: Mapped[intpk]`` declare a primary key. Which object ``intpk``
names depends on the module and on where the class is defined in it, so it
is resolved like Python resolves the name when the class body runs:

- the module's last module-level binding of the name *before the class*
  counts: an alias (``X = Annotated[...]``, ``X = other_alias``), an import,
  a star import, or anything else (a function, a class, ``X = int``);
- an import is followed into the scanned file it names; a star import
  provides the names that module exports (``__all__``, else its public names);
- an alias built on another one (``Annotated[intpk, ...]``) resolves that one
  where the alias is defined;
- a name the module does not bind at all (e.g. imported under
  ``TYPE_CHECKING``) falls back to an alias of that name defined identically
  wherever it is defined, unless a model class has that name.
"""

import ast
from pathlib import Path
from types import MappingProxyType
from typing import Dict, Iterable, List, Mapping, NamedTuple, Set, Tuple

from .annotations import defines_column_alias, expand_aliases

#: ``_find_module`` result for an absolute import several scanned files match.
_AMBIGUOUS = Path("<ambiguous>")


class _Binding(NamedTuple):
    """One module-level binding of a name."""

    #: ``"alias"`` (a possible alias value), ``"import"`` or ``"other"``.
    kind: str
    #: Line of the statement; a class only sees bindings before its own line.
    line: int
    #: The assigned value (``"alias"``).
    value: ast.expr | None = None
    #: The imported module as written, ``None`` for ``from . import x`` (``"import"``).
    module: str | None = None
    #: Leading dots of a relative import (``"import"``).
    level: int = 0
    #: The name imported from that module (``"import"``).
    original: str = ""


class AliasResolver:
    """Resolves column type aliases per scanned module.

    Args:
        trees: Each scanned file's syntax tree.
        classes: Names of the parsed model classes; the by-name fallback never
            turns one into an alias.
    """

    def __init__(self, trees: Mapping[Path, ast.Module], classes: Iterable[str]):
        self._trees = trees
        self._classes = set(classes)
        self._events: Dict[Path, List[Tuple[str, _Binding]]] = {}
        self._scopes: Dict[Tuple[Path, int | None], Dict[str, _Binding]] = {}
        self._scoping: Set[Path] = set()
        self._modules: Dict[Tuple[Path, str | None, int], Path | None] = {}
        self._resolved: Dict[Tuple[Path, str, int | None], ast.expr | None] = {}
        #: Cycle cut-offs so far; a result computed across one is not cached.
        self._cycles = 0
        self._views: Dict[Tuple[Path, int | None], Mapping[str, ast.expr]] = {}
        self._fallback: Dict[str, ast.expr] | None = None
        self._suffixes: Dict[Tuple[str, ...], List[Path]] | None = None

    def aliases_for(self, file: Path | None, line: int | None = None) -> Mapping[str, ast.expr]:
        """Alias name -> fully expanded ``Annotated[...]``, as seen at ``line`` of ``file``."""
        if file is None or file not in self._trees:
            return MappingProxyType(dict(self._fallback_aliases()))
        key = (file, line)
        view = self._views.get(key)
        if view is not None:
            return view
        scope = self._scope(file, line)
        result: Dict[str, ast.expr] = {}
        for name, binding in scope.items():
            if binding.kind != "other":
                value = self._resolve(file, name, line, ())
                if value is not None:
                    result[name] = value
        for name, value in self._fallback_aliases().items():
            if name not in scope:  # bound names, also via `*`, never fall back
                result[name] = value
        view = MappingProxyType(result)
        self._views[key] = view
        return view

    # -- module scope ----------------------------------------------------------

    def _module_events(self, file: Path) -> List[Tuple[str, _Binding]]:
        """``(name, binding)`` per module-level binding, in statement order.

        A star import is recorded as name ``"*"`` and expanded by ``_scope``.
        """
        events = self._events.get(file)
        if events is not None:
            return events
        events = []
        for node in self._trees[file].body:
            line = node.lineno
            if isinstance(node, ast.Assign):
                if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                    events.append((node.targets[0].id, self._assigned(node.value, line)))
                else:  # chained or unpacking: whatever it binds is not an alias
                    events.extend(
                        (sub.id, _Binding("other", line))
                        for target in node.targets
                        for sub in ast.walk(target)
                        if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store)
                    )
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.value is not None:  # a bare `x: int` binds nothing
                    events.append((node.target.id, self._assigned(node.value, line)))
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    binding = _Binding(
                        "import", line, module=node.module, level=node.level, original=alias.name
                    )
                    events.append(
                        ("*" if alias.name == "*" else alias.asname or alias.name, binding)
                    )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname or alias.name.split(".")[0]
                    events.append((name, _Binding("other", line)))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                events.append((node.name, _Binding("other", line)))
            elif type(node).__name__ == "TypeAlias":
                # PEP 695 `type X = ...`: SQLAlchemy takes no mapped_column() from it.
                alias_name = getattr(node, "name", None)
                if isinstance(alias_name, ast.Name):
                    events.append((alias_name.id, _Binding("other", line)))
        self._events[file] = events
        return events

    @staticmethod
    def _assigned(value: ast.expr, line: int) -> _Binding:
        """``X = Annotated[...]`` or ``X = other_alias`` may be an alias; anything else is not."""
        if isinstance(value, (ast.Subscript, ast.Name)):
            return _Binding("alias", line, value=value)
        return _Binding("other", line)

    def _scope(self, file: Path, line: int | None) -> Dict[str, _Binding]:
        """Each name's last module-level binding before ``line`` (all of them if None)."""
        key = (file, line)
        cached = self._scopes.get(key)
        if cached is not None:
            return cached
        scope: Dict[str, _Binding] = {}
        self._scoping.add(file)
        try:
            for name, binding in self._module_events(file):
                if line is not None and binding.line >= line:
                    break
                if name != "*":
                    scope[name] = binding
                    continue
                target = self._find_module(file, binding.module, binding.level)
                if target is None or target is _AMBIGUOUS or target in self._scoping:
                    continue
                for exported in self._exports(target):
                    scope[exported] = binding._replace(original=exported)
        finally:
            self._scoping.discard(file)
        self._scopes[key] = scope
        return scope

    def _exports(self, file: Path) -> List[str]:
        """What ``from <file> import *`` binds: a literal ``__all__``, else public names."""
        for node in self._trees[file].body:
            if (
                isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets)
                and isinstance(node.value, (ast.List, ast.Tuple))
            ):
                return [
                    elt.value
                    for elt in node.value.elts
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                ]
        return [name for name in self._scope(file, None) if not name.startswith("_")]

    # -- resolution ----------------------------------------------------------------

    def _resolve(
        self, file: Path, name: str, line: int | None, stack: Tuple[Tuple[Path, str], ...]
    ) -> ast.expr | None:
        """The expanded column alias ``name`` refers to at ``line`` of ``file``, or None."""
        key = (file, name, line)
        if key in self._resolved:
            return self._resolved[key]
        if (file, name) in stack:
            self._cycles += 1  # results computed under this cut-off depend on the stack
            return None
        cycles = self._cycles
        result = None
        binding = self._scope(file, line).get(name)
        if binding is not None:
            result = self._resolve_binding(file, binding, stack + ((file, name),))
        if self._cycles == cycles:
            self._resolved[key] = result
        return result

    def _resolve_binding(
        self, file: Path, binding: _Binding, stack: Tuple[Tuple[Path, str], ...]
    ) -> ast.expr | None:
        if binding.kind == "import":
            target = self._find_module(file, binding.module, binding.level)
            if target is _AMBIGUOUS:  # several scanned modules match: by name
                return self._fallback_aliases().get(binding.original)
            if target is None:  # not a scanned module (stdlib, third party)
                return None
            return self._resolve(target, binding.original, None, stack)
        if binding.kind != "alias" or binding.value is None:
            return None
        # Names inside the alias resolve where, and when, it is defined (#249).
        local: Dict[str, ast.expr] = {}
        for sub in ast.walk(binding.value):
            if isinstance(sub, ast.Name) and sub.id not in local:
                inner = self._resolve(file, sub.id, binding.line, stack)
                if inner is not None:
                    local[sub.id] = inner
        expanded = expand_aliases(binding.value, local)
        return expanded if defines_column_alias(expanded) else None

    def _find_module(self, file: Path, module: str | None, level: int) -> Path | None:
        """The scanned file an import refers to, ``_AMBIGUOUS``, or None (not scanned)."""
        key = (file, module, level)
        if key in self._modules:
            return self._modules[key]
        parts = module.split(".") if module else []
        found: Path | None = None
        if level:
            base = file.parent
            for _ in range(level - 1):
                base = base.parent
            if parts:
                stem = base.joinpath(*parts)
                candidates = [stem.parent / f"{stem.name}.py", stem / "__init__.py"]
            else:  # `from . import x`: the package itself
                candidates = [base / "__init__.py"]
            found = next((c for c in candidates if c in self._trees), None)
        elif parts:
            matches = self._suffix_index().get(tuple(parts), [])
            if len(matches) > 1:
                # Prefer the module whose package root contains the importing file.
                matches = [m for m in matches if self._root_contains(m, len(parts), file)]
            found = matches[0] if len(matches) == 1 else (_AMBIGUOUS if matches else None)
            if found is None and self._suffix_index().get(tuple(parts)):
                found = _AMBIGUOUS
        self._modules[key] = found
        return found

    def _suffix_index(self) -> Dict[Tuple[str, ...], List[Path]]:
        """Dotted-module suffix -> scanned files, e.g. ``("app", "models")``."""
        if self._suffixes is None:
            index: Dict[Tuple[str, ...], List[Path]] = {}
            for path in self._trees:
                dotted = (
                    path.parent.parts if path.name == "__init__.py" else path.with_suffix("").parts
                )
                for size in range(1, len(dotted) + 1):
                    index.setdefault(tuple(dotted[-size:]), []).append(path)
            self._suffixes = index
        return self._suffixes

    @staticmethod
    def _root_contains(module_file: Path, depth: int, importer: Path) -> bool:
        """Whether ``importer`` lies under the root ``module_file`` is imported from."""
        dotted = (
            module_file.parent.parts
            if module_file.name == "__init__.py"
            else module_file.with_suffix("").parts
        )
        root = dotted[: len(dotted) - depth]
        return importer.parts[: len(root)] == root

    def _fallback_aliases(self) -> Dict[str, ast.expr]:
        """Aliases by name, for names a module does not bind (defined identically everywhere)."""
        if self._fallback is not None:
            return self._fallback
        self._fallback = {}  # guards re-entry from an ambiguous import while computing
        found: Dict[str, List[ast.expr]] = {}
        for file in self._trees:
            for name, binding in self._scope(file, None).items():
                if binding.kind == "alias" and name not in self._classes:
                    value = self._resolve(file, name, None, ())
                    if value is not None:
                        found.setdefault(name, []).append(value)
        self._fallback = {
            name: values[0]
            for name, values in found.items()
            if len({ast.dump(v) for v in values}) == 1
        }
        self._resolved.clear()  # may hold results computed without the fallback
        return self._fallback
