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
from bisect import bisect_left
from pathlib import Path
from types import MappingProxyType
from typing import Dict, Iterable, List, Mapping, NamedTuple, Set, Tuple

from .annotations import defines_column_alias, expand_aliases, parse_quoted

#: A name looked up at a line of a file (``None``: the whole module).
_Lookup = Tuple[Path, str, "int | None"]

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
        #: Per file, each name's bindings in statement order (star imports expanded).
        self._histories: Dict[Path, Dict[str, List[_Binding]]] = {}
        #: Per file, names with a binding that may be an alias.
        self._candidates: Dict[Path, List[str]] = {}
        self._scoping: Set[Path] = set()
        #: Star-import cut-offs so far; a history built across one is not cached.
        self._star_cycles = 0
        self._resolved_paths: Dict[Path, Path] = {}
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
        result: Dict[str, ast.expr] = {}
        for name in self._candidate_names(file):
            value = self._resolve(file, name, line, ())
            if value is not None:
                result[name] = value
        for name, value in self._fallback_aliases().items():
            # A name bound before the class (also via `*`) never falls back.
            if name not in result and self._binding_at(file, name, line) is None:
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

    def _history(self, file: Path) -> Dict[str, List[_Binding]]:
        """Each name's module-level bindings in statement order, star imports expanded.

        Not cached while a circular star import cut it short, so the cut-off
        never becomes a permanently missing binding.
        """
        cached = self._histories.get(file)
        if cached is not None:
            return cached
        history: Dict[str, List[_Binding]] = {}
        cycles = self._star_cycles
        self._scoping.add(file)
        try:
            for name, binding in self._module_events(file):
                if name != "*":
                    history.setdefault(name, []).append(binding)
                    continue
                target = self._find_module(file, binding.module, binding.level)
                if target is None or target is _AMBIGUOUS:
                    continue
                if target in self._scoping:
                    self._star_cycles += 1
                    continue
                for exported in self._exports(target):
                    history.setdefault(exported, []).append(binding._replace(original=exported))
        finally:
            self._scoping.discard(file)
        if self._star_cycles == cycles:
            self._histories[file] = history
        return history

    def _candidate_names(self, file: Path) -> List[str]:
        """Names with a binding in ``file`` that may be an alias (few, usually)."""
        cached = self._candidates.get(file)
        if cached is not None:
            return cached
        names = [
            name
            for name, bindings in self._history(file).items()
            if any(b.kind != "other" for b in bindings)
        ]
        if file in self._histories:  # only once the history itself is final
            self._candidates[file] = names
        return names

    def _binding_at(self, file: Path, name: str, line: int | None) -> _Binding | None:
        """The last module-level binding of ``name`` before ``line`` (any, if None)."""
        bindings = self._history(file).get(name)
        if not bindings:
            return None
        if line is None:
            return bindings[-1]
        index = bisect_left([b.line for b in bindings], line)
        return bindings[index - 1] if index else None

    def _exports(self, file: Path) -> List[str]:
        """What ``from <file> import *`` binds: the last literal ``__all__``, else public names."""
        exports: List[str] | None = None
        for node in self._trees[file].body:
            targets = (
                node.targets
                if isinstance(node, ast.Assign)
                else [node.target]
                if isinstance(node, ast.AnnAssign)
                else []
            )
            if any(isinstance(t, ast.Name) and t.id == "__all__" for t in targets):
                value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
                if value is None:  # `__all__: list[str]` alone binds nothing
                    continue
                exports = (
                    [
                        elt.value
                        for elt in value.elts
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                    ]
                    if isinstance(value, (ast.List, ast.Tuple))
                    else None  # not a literal: unknown, fall back to public names
                )
        if exports is not None:
            return exports
        return [name for name in self._history(file) if not name.startswith("_")]

    # -- resolution ----------------------------------------------------------------

    def _resolve(
        self, file: Path, name: str, line: int | None, stack: Tuple[_Lookup, ...]
    ) -> ast.expr | None:
        """The expanded column alias ``name`` refers to at ``line`` of ``file``, or None.

        The stack holds ``(file, name, line)``, so ``intpk = Annotated[intpk, ...]``
        can refer to the earlier ``intpk`` while a real cycle (mutual imports)
        still stops.
        """
        key = (file, name, line)
        if key in self._resolved:
            return self._resolved[key]
        if key in stack:
            self._cycles += 1  # results computed under this cut-off depend on the stack
            return None
        cycles = self._cycles
        result = None
        binding = self._binding_at(file, name, line)
        if binding is not None:
            result = self._resolve_binding(file, binding, stack + (key,))
        if self._cycles == cycles:
            self._resolved[key] = result
        return result

    def _resolve_binding(
        self, file: Path, binding: _Binding, stack: Tuple[_Lookup, ...]
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
        # Names inside the alias resolve where, and when, it is defined (#249),
        # also inside a quoted base (`Annotated["intpk", ...]`).
        local: Dict[str, ast.expr] = {}
        for name in self._referenced_names(binding.value):
            if name not in local:
                inner = self._resolve(file, name, binding.line, stack)
                if inner is not None:
                    local[name] = inner
        expanded = expand_aliases(binding.value, local)
        return expanded if defines_column_alias(expanded) else None

    @classmethod
    def _referenced_names(cls, node: ast.expr) -> List[str]:
        """Names ``node`` mentions, also inside quoted type expressions."""
        names: List[str] = []
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name):
                names.append(sub.id)
            elif isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                parsed = parse_quoted(sub)
                if parsed is not None:
                    names.extend(cls._referenced_names(parsed))
        return names

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
                # A package wins over a module file of the same name, as in Python.
                candidates = [stem / "__init__.py", stem.parent / f"{stem.name}.py"]
            else:  # `from . import x`: the package itself
                candidates = [base / "__init__.py"]
            found = next((c for c in candidates if c in self._trees), None)
        elif parts:
            # Only a module whose import root contains the importing file can be
            # what it imports: a scanned `pkg/uuid.py` is not `import uuid`.
            matches = [
                m
                for m in self._suffix_index().get(tuple(parts), [])
                if self._root_contains(m, len(parts), file)
            ]
            packages = {m.parent for m in matches if m.name == "__init__.py"}
            # `coltypes.py` beside a `coltypes/` package is shadowed by it.
            matches = [
                m for m in matches if m.name == "__init__.py" or m.with_suffix("") not in packages
            ]
            found = matches[0] if len(matches) == 1 else (_AMBIGUOUS if matches else None)
        self._modules[key] = found
        return found

    def _suffix_index(self) -> Dict[Tuple[str, ...], List[Path]]:
        """Dotted-module suffix -> scanned files, e.g. ``("app", "models")``."""
        if self._suffixes is None:
            index: Dict[Tuple[str, ...], List[Path]] = {}
            for path in self._trees:
                dotted = self._dotted(path)
                for size in range(1, len(dotted) + 1):
                    index.setdefault(tuple(dotted[-size:]), []).append(path)
            self._suffixes = index
        return self._suffixes

    def _absolute(self, path: Path) -> Path:
        """``path`` resolved, so a relative scan root (``erdify .``) keeps its packages."""
        resolved = self._resolved_paths.get(path)
        if resolved is None:
            resolved = self._resolved_paths[path] = path.resolve()
        return resolved

    def _dotted(self, path: Path) -> Tuple[str, ...]:
        """The module path parts of a scanned file (``app/models.py`` -> app, models)."""
        absolute = self._absolute(path)
        return (
            absolute.parent.parts
            if absolute.name == "__init__.py"
            else absolute.with_suffix("").parts
        )

    def _root_contains(self, module_file: Path, depth: int, importer: Path) -> bool:
        """Whether ``importer`` lies under the root ``module_file`` is imported from."""
        dotted = self._dotted(module_file)
        root = dotted[: len(dotted) - depth]
        return self._absolute(importer).parts[: len(root)] == root

    #: Upper bound on fallback rounds; conflicting definitions could otherwise
    #: keep changing the table (in practice it settles after a few rounds).
    _FALLBACK_ROUNDS = 10

    def _fallback_aliases(self) -> Dict[str, ast.expr]:
        """Aliases by name, for names a module does not bind (defined identically everywhere).

        Computed to a fixed point: an alias may itself depend on the fallback,
        e.g. ``UserId = intpk`` where ``intpk`` comes through an ambiguous
        import (#254), so rounds repeat until the table stops changing.
        """
        if self._fallback is not None:
            return self._fallback
        table: Dict[str, ast.expr] = {}
        for _ in range(self._FALLBACK_ROUNDS):
            self._fallback = table  # what ambiguous imports see during this round
            self._resolved.clear()  # results of the last round used the old table
            found: Dict[str, List[ast.expr]] = {}
            for file in self._trees:
                for name, bindings in self._history(file).items():
                    if bindings[-1].kind == "alias" and name not in self._classes:
                        value = self._resolve(file, name, None, ())
                        if value is not None:
                            found.setdefault(name, []).append(value)
            next_table = {
                name: values[0]
                for name, values in found.items()
                if len({ast.dump(v) for v in values}) == 1
            }
            if self._dumped(next_table) == self._dumped(table):
                break
            table = next_table
        self._fallback = table
        self._resolved.clear()
        return self._fallback

    @staticmethod
    def _dumped(table: Mapping[str, ast.expr]) -> Dict[str, str]:
        return {name: ast.dump(value) for name, value in table.items()}
