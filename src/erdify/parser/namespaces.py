"""Same-name model classes in different modules (#367).

Classes are indexed by name, so two model classes called ``Address`` in
``billing/models.py`` and ``shipping/models.py`` used to be one entity (the
one scanned last). :func:`namespace_models` keeps them apart: each colliding
definition gets an internal name of its own (``Address__erdify1``), and every
reference to ``Address`` in a scanned file is rewritten to the definition that
file means. The rest of the parser then works as before, by name. The
internal name never reaches the output: default table names read the original
name (:func:`~erdify.parser.common.original_class_name`), and the entities are
renamed to ``module.Class`` (``billing.models.Address``) once they are built.

A reference means the definition in its own file, else the one its imports
name: ``from billing.models import Address [as A]``, a star import, or an
attribute (``models.Address``, ``billing.models.Address``) whose module path
ends a candidate's module. A string reference (``"Address"``,
``relationship("billing.models.Address")``, Django's ``"billing.Address"`` /
``ForeignKey("Address")``) is resolved the same way, a Django app label by
the candidates' apps. A reference none of this resolves is left unresolved
(no edge) and reported on stderr.
"""

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Mapping, Sequence, Tuple

from .common import is_module_file, module_name
from .dialects.django_apps import app_label, app_package

#: Calls whose first argument (or ``to=`` / ``argument=``) names a model.
_REFERENCE_CALLS = {
    "relationship",
    "Relationship",
    "ForeignKey",
    "OneToOneField",
    "ManyToManyField",
    "ForeignObject",
}
_REFERENCE_KEYWORDS = {"to", "argument"}


@dataclass
class Namespaced:
    """What :func:`namespace_models` did.

    Attributes:
        display: Internal class name -> the entity name to draw
            (``billing.models.Address``).
        unresolved: ``(file, name)`` of each reference to a colliding name
            that no definition could be chosen for.
    """

    display: Dict[str, str] = field(default_factory=dict)
    unresolved: List[Tuple[Path, str, List[Path]]] = field(default_factory=list)


@dataclass
class _Candidate:
    node: ast.ClassDef
    file: Path
    internal: str
    module: str


def namespace_models(
    groups: Mapping[str, Sequence[Tuple[ast.ClassDef, Path]]],
    trees: Mapping[Path, ast.Module],
    taken: Sequence[str],
    base: Path,
) -> Namespaced:
    """Rename each colliding definition and rewrite the references to it.

    Args:
        groups: Class name -> its top-level model definitions, one per file
            (at least two files).
        trees: Every scanned file's syntax tree; rewritten in place.
        taken: Class names already in use (the internal names avoid them).
        base: The scanned directory, for names of files outside a package.

    Returns:
        The display name of each internal name, and the references left
        unresolved.
    """
    result = Namespaced()
    used = set(taken)
    candidates: Dict[str, List[_Candidate]] = {}
    counter = 0
    for name, definitions in groups.items():
        modules = [module_name(path) for _, path in definitions]
        if len(set(modules)) < len(modules):  # e.g. a/models.py and b/models.py
            modules = [_relative_module(path, base) for _, path in definitions]
        for (node, path), module in zip(definitions, modules):
            counter += 1
            internal = f"{name}__erdify{counter}"
            while internal in used:
                counter += 1
                internal = f"{name}__erdify{counter}"
            used.add(internal)
            candidates.setdefault(name, []).append(_Candidate(node, path, internal, module))
            result.display[internal] = f"{module}.{name}"

    for path, tree in trees.items():
        _Rewriter(path, tree, candidates, result).rewrite()
    for group in candidates.values():
        for candidate in group:
            candidate.node.name = candidate.internal
    return result


def _relative_module(path: Path, base: Path) -> str:
    """``a/models.py`` under ``base`` -> ``a.models`` (a scanned file is under ``base``)."""
    parts = list(path.resolve().relative_to(base.resolve()).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


class _Rewriter:
    """Rewrites one file's references to colliding class names."""

    def __init__(
        self,
        path: Path,
        tree: ast.Module,
        candidates: Mapping[str, List[_Candidate]],
        result: Namespaced,
    ):
        self.path = path
        self.tree = tree
        self.candidates = candidates
        self.result = result
        #: Name bound in this file -> internal name it means.
        self.bindings: Dict[str, str] = {}
        #: Module alias (``import billing.models as bm``) -> dotted module.
        self.module_aliases: Dict[str, str] = {}
        self._reported: set[str] = set()

    def rewrite(self) -> None:
        self._bind()
        transformer = _Transformer(self)
        transformer.visit(self.tree)

    def _bind(self) -> None:
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ImportFrom):
                self._bind_from(node)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.asname:
                        self.module_aliases[alias.asname] = alias.name
        for name, group in self.candidates.items():
            own = [c for c in group if c.file == self.path]
            if own:
                self.bindings[name] = own[-1].internal

    def _bind_from(self, node: ast.ImportFrom) -> None:
        source = (node.level, node.module or "")
        for alias in node.names:
            names = list(self.candidates) if alias.name == "*" else [alias.name]
            for name in names:
                group = self.candidates.get(name)
                if group is None:
                    continue
                found = [c for c in group if is_module_file(c.file, self.path, source)]
                if len(found) != 1:
                    continue
                bound = name if alias.name == "*" else (alias.asname or name)
                self.bindings[bound] = found[0].internal

    def name(self, name: str) -> str | None:
        """The internal name ``name`` means here, or None (reported) if it can't tell."""
        internal = self.bindings.get(name)
        if internal is None and name in self.candidates:
            self._report(name)
        return internal

    def dotted(self, dotted: str) -> str | None:
        """The internal name a ``module.path.Class`` reference means, if unique."""
        module, _, name = dotted.rpartition(".")
        group = self.candidates.get(name)
        if group is None or not module:
            return None
        head, _, rest = module.partition(".")
        if head in self.module_aliases:
            module = ".".join(p for p in (self.module_aliases[head], rest) if p)
        found = [c for c in group if c.module == module or c.module.endswith("." + module)]
        if len(found) == 1:
            return found[0].internal
        if not found:
            found = [c for c in group if _app(c.file) == module]  # Django "app.Model"
            if len(found) == 1:
                return found[0].internal
        self._report(name)
        return None

    def string(self, value: str, *, django: bool) -> str | None:
        """A string reference rewritten, or None when it names no colliding class."""
        if "." in value:
            return self.dotted(value) if value.rpartition(".")[2] in self.candidates else None
        if value not in self.candidates:
            return None
        internal = self.bindings.get(value)
        if internal is None and django:  # Django: a model of the same app
            app = _app(self.path)
            found = [c for c in self.candidates[value] if _app(c.file) == app]
            internal = found[0].internal if len(found) == 1 else None
        if internal is None:
            self._report(value)
        return internal

    def _report(self, name: str) -> None:
        if name not in self._reported:
            self._reported.add(name)
            files = [c.file for c in self.candidates[name]]
            self.result.unresolved.append((self.path, name, files))


def _app(path: Path) -> str:
    """The Django app label of a file's app (its package name outside Django)."""
    return app_label(app_package(path))


class _Transformer(ast.NodeTransformer):
    def __init__(self, rewriter: _Rewriter):
        self.r = rewriter

    def visit_Name(self, node: ast.Name) -> ast.AST:
        if not isinstance(node.ctx, ast.Load):
            return node
        if node.id in self.r.candidates or node.id in self.r.bindings:
            internal = self.r.name(node.id)
            if internal is not None:
                return ast.copy_location(ast.Name(id=internal, ctx=node.ctx), node)
        return node

    def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
        if node.attr in self.r.candidates and isinstance(node.ctx, ast.Load):
            dotted = _dotted(node)
            if dotted is not None:
                internal = self.r.dotted(dotted)
                if internal is not None:
                    return ast.copy_location(ast.Name(id=internal, ctx=ast.Load()), node)
        self.generic_visit(node)
        return node

    def visit_AnnAssign(self, node: ast.AnnAssign) -> ast.AST:
        node.annotation = self._annotation(node.annotation)
        if node.value is not None:
            node.value = self.visit(node.value)
        return node

    def visit_arg(self, node: ast.arg) -> ast.AST:
        if node.annotation is not None:
            node.annotation = self._annotation(node.annotation)
        return node

    def visit_Call(self, node: ast.Call) -> ast.AST:
        name = _call_name(node.func)
        self.generic_visit(node)
        if name in _REFERENCE_CALLS:
            django = name != "relationship" and name != "Relationship"
            if node.args:
                node.args[0] = self._string(node.args[0], django=django)
            for kw in node.keywords:
                if kw.arg in _REFERENCE_KEYWORDS:
                    kw.value = self._string(kw.value, django=django)
        return node

    def _string(self, value: ast.expr, *, django: bool) -> ast.expr:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            internal = self.r.string(value.value, django=django)
            if internal is not None:
                return ast.copy_location(ast.Constant(value=internal), value)
        return value

    def _annotation(self, annotation: ast.expr) -> ast.expr:
        """An annotation with its names and quoted forward references rewritten."""
        visited: ast.expr = self.visit(annotation)
        rewritten: ast.expr = _StringAnnotations(self).visit(visited)
        return rewritten


class _StringAnnotations(ast.NodeTransformer):
    """Rewrites quoted forward references (``"Address"``, ``"list[Address]"``)."""

    def __init__(self, outer: _Transformer):
        self.outer = outer

    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        if not isinstance(node.value, str):
            return node
        try:
            parsed = ast.parse(node.value, mode="eval").body
        except SyntaxError:
            return node
        rewritten = self.outer.visit(parsed)
        text = ast.unparse(rewritten)
        if text == ast.unparse(ast.parse(node.value, mode="eval").body):
            return node
        return ast.copy_location(ast.Constant(value=text), node)


def _dotted(node: ast.expr) -> str | None:
    """``a.b.C`` as text, if it is a chain of names."""
    parts: List[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return ".".join(reversed(parts))


def _call_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


#: An internal name in text (a type string, a warning).
INTERNAL = re.compile(r"\b\w+__erdify\d+\b")


def display_text(text: str, display: Mapping[str, str]) -> str:
    """``text`` with every internal class name replaced by its display name."""
    return INTERNAL.sub(lambda m: display.get(m.group(0), m.group(0)), text)
