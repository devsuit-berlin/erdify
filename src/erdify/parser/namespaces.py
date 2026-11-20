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
name: ``from billing.models import Address [as A]`` (also re-exported by a
package's ``__init__.py``: ``from .address import Address`` or ``from
.address import *``), a star import, or an attribute (``models.Address``
after ``from billing import models``, ``billing.models.Address``) whose
module path ends a candidate's module. A string reference (``"Address"``,
``relationship("billing.models.Address")``, Django's ``"billing.Address"`` /
``ForeignKey("Address")``, model names in any case) is resolved the same
way, a Django app label by the candidates' ``Meta.app_label`` or app, a bare
Django name in the referencing model's app (its ``Meta.app_label``, else its
file's app) first. ``Literal[...]`` values, ``Annotated`` metadata and
``ForeignKey`` strings outside Django files (SQLAlchemy's
``"table.column"``) are not references. A reference several definitions
could mean is left unresolved (no edge) and reported on stderr; a name
imported from a module that isn't scanned, or from a scanned one that binds
it itself, or bound by the file itself, is not a reference to them.
"""

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Mapping, Sequence, Tuple

from .common import is_module_file, module_name
from .dialects.django_apps import app_label, app_package

#: :meth:`_Rewriter._imported` results besides an internal name.
_AMBIGUOUS = "\0ambiguous"
_OUTSIDE = "\0outside"
_ABSENT = "\0absent"

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
        unresolved: ``(file, name, candidate files)`` of each reference to a
            colliding name that no definition could be chosen for.
    """

    display: Dict[str, str] = field(default_factory=dict)
    unresolved: List[Tuple[Path, str, List[Path]]] = field(default_factory=list)


@dataclass
class _Candidate:
    node: ast.ClassDef
    file: Path
    internal: str
    module: str

    @property
    def app(self) -> str:
        """The Django app label: ``Meta.app_label``, else the file's app."""
        return _meta_app_label(self.node) or _app(self.file)


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
        _Rewriter(path, tree, candidates, result, trees).rewrite()
    for name, group in candidates.items():
        for candidate in group:
            # Every module-level definition of the name in that file (an
            # earlier one it replaces, one under `if`) takes its internal name,
            # so none is left under the bare name.
            for node in _module_level_classes(trees[candidate.file]):
                if node.name == name:
                    node.name = candidate.internal
            candidate.node.name = candidate.internal
    return result


def _module_level_classes(tree: ast.Module) -> List[ast.ClassDef]:
    """The classes a module defines at its top level, also under ``if`` / ``try`` / ``with``."""
    found: List[ast.ClassDef] = []
    pending: List[ast.stmt] = list(tree.body)
    while pending:
        stmt = pending.pop(0)
        if isinstance(stmt, ast.ClassDef):
            found.append(stmt)
        elif not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.iter_child_nodes(stmt):
                if isinstance(child, ast.stmt):
                    pending.append(child)
    return found


def _relative_module(path: Path, base: Path) -> str:
    """``a/models.py`` under ``base`` -> ``a.models``."""
    try:
        rel = path.relative_to(base)
    except ValueError:  # a symlink resolved outside the scanned directory
        rel = Path(path.name)
    parts = list(rel.with_suffix("").parts)
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
        trees: Mapping[Path, ast.Module],
    ):
        self.path = path
        self.tree = tree
        self.trees = trees
        #: A file that imports from Django: its ForeignKey strings are model
        #: references (SQLAlchemy's are ``table.column``).
        self.django = any(
            (isinstance(n, ast.ImportFrom) and (n.module or "").split(".")[0] == "django")
            or (
                isinstance(n, ast.Import) and any(a.name.split(".")[0] == "django" for a in n.names)
            )
            for n in ast.walk(tree)
        )
        self.candidates = candidates
        self.result = result
        #: Name bound in this file -> internal name it means.
        self.bindings: Dict[str, str] = {}
        #: Module alias (``import billing.models as bm``, ``from billing import
        #: models``) -> dotted module.
        self.module_aliases: Dict[str, str] = {}
        #: Names imported from a module that isn't scanned: not a reference to
        #: a scanned class, so never reported.
        self.elsewhere: set[str] = set()
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
        # A name this file binds itself otherwise (a plain class, an
        # assignment): its references mean that, not a scanned model.
        for target in _own_names(self.tree.body):
            if target in self.candidates and target not in self.bindings:
                self.elsewhere.add(target)

    def _bind_from(self, node: ast.ImportFrom) -> None:
        source = (node.level, node.module or "")
        everyone = [c for group in self.candidates.values() for c in group]
        for alias in node.names:
            if alias.name != "*":
                # `from billing import models [as bm]`: a module of candidates.
                sub = (node.level, ".".join(p for p in (node.module, alias.name) if p))
                modules = {c.module for c in everyone if is_module_file(c.file, self.path, sub)}
                if len(modules) == 1:
                    self.module_aliases[alias.asname or alias.name] = modules.pop()
            names = list(self.candidates) if alias.name == "*" else [alias.name]
            for name in names:
                group = self.candidates.get(name)
                if group is None:
                    continue
                bound = name if alias.name == "*" else (alias.asname or name)
                internal = self._imported(name, self.path, source, depth=0)
                if internal == _OUTSIDE:
                    if alias.name != "*":
                        # From a module that isn't scanned, or one that binds
                        # the name itself: not one of the same-name classes.
                        self.elsewhere.add(bound)
                elif internal not in (_AMBIGUOUS, _ABSENT):  # those are reported on use
                    self.bindings[bound] = internal

    def _imported(self, name: str, importer: Path, source: Tuple[int, str], depth: int) -> str:
        """What ``from <source> import name`` means, following re-exports.

        ``from shop.models import Address``, where ``shop/models/__init__.py``
        does ``from .address import Address`` (or ``from .address import *``),
        means the class in ``shop/models/address.py``.

        Returns:
            A candidate's internal name; :data:`_OUTSIDE` when the import names
            none of them (a module that isn't scanned, or a scanned one that
            binds the name itself: a class, function or assignment of its
            own); :data:`_ABSENT` when the scanned module has no such name;
            :data:`_AMBIGUOUS` when several candidates or modules could be
            meant, or it is re-exported in a way erdify doesn't follow.
        """
        group = self.candidates[name]
        found = [c for c in group if is_module_file(c.file, importer, source)]
        if len(found) == 1:
            return found[0].internal
        if found:
            return _AMBIGUOUS
        modules = [path for path in self.trees if is_module_file(path, importer, source)]
        if not modules:
            return _OUTSIDE
        if depth > 4:
            return _AMBIGUOUS
        results = [self._in_module(name, module, depth) for module in modules]
        reached = {r for r in results if r not in (_OUTSIDE, _ABSENT)}
        if not reached:
            # A module that has no such name: reported where it is used; one
            # of several (`from utils import X` matching two utils.py) that
            # reach none of the classes: not a reference to them.
            return _ABSENT if results == [_ABSENT] else _OUTSIDE
        if len(modules) == 1 and len(reached) == 1:
            return reached.pop()
        return _AMBIGUOUS

    def _in_module(self, name: str, module: Path, depth: int) -> str:
        """What ``name`` is in a scanned module (see :meth:`_imported`)."""
        body = self.trees[module].body
        if name in _own_names(body):
            return _OUTSIDE
        results: List[str] = []
        star_outside = False
        for stmt in body:
            if not isinstance(stmt, ast.ImportFrom):
                continue
            inner = (stmt.level, stmt.module or "")
            if any(alias.name == name and alias.asname in (None, name) for alias in stmt.names):
                results.append(self._imported(name, module, inner, depth + 1))
            elif any(alias.name == "*" for alias in stmt.names):
                result = self._imported(name, module, inner, depth + 1)
                if result == _OUTSIDE:
                    star_outside = True  # may come from a module that isn't scanned
                elif result != _ABSENT:  # a star of other names
                    results.append(result)
        if not results:
            # Bound some other way at module level (under `if` / `try`,
            # renamed): can't follow.
            if _binds_at_module_level(body, name):
                return _AMBIGUOUS
            return _OUTSIDE if star_outside else _ABSENT
        if _AMBIGUOUS in results or len(set(results)) > 1:
            return _AMBIGUOUS
        return results[0]

    def name(self, name: str) -> str | None:
        """The internal name ``name`` means here, or None (reported) if it can't tell."""
        internal = self.bindings.get(name)
        if internal is None and name in self.candidates and name not in self.elsewhere:
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
        if not found:
            found = [c for c in group if c.app == module]  # Django "app.Model"
        if len(found) == 1:
            return found[0].internal
        if found:  # several match: can't tell
            self._report(name)
        return None

    def string(self, value: str, *, django: bool, owner: ast.ClassDef | None = None) -> str | None:
        """A string reference rewritten, or None when it names no colliding class.

        Django matches a model name without regard to case
        (``"billing.address"``) and resolves a bare one in the referencing
        model's app first, as Django does.
        """
        module, dot, last = value.rpartition(".")
        name = self._candidate(last, django)
        if name is None:
            return None
        if dot:
            return self.dotted(f"{module}.{name}")
        if django:
            app = (_meta_app_label(owner) if owner is not None else None) or _app(self.path)
            found = [c for c in self.candidates[name] if c.app == app]
            if len(found) == 1:
                return found[0].internal
        internal = self.bindings.get(name)
        if internal is None:
            self._report(name)
        return internal

    def _candidate(self, name: str, django: bool) -> str | None:
        """The colliding class name ``name`` names (Django: also in another case)."""
        if name in self.candidates:
            return name
        if django:
            found = [n for n in self.candidates if n.lower() == name.lower()]
            if len(found) == 1:
                return found[0]
        return None

    def _report(self, name: str) -> None:
        if name not in self._reported:
            self._reported.add(name)
            files = [c.file for c in self.candidates[name]]
            self.result.unresolved.append((self.path, name, files))


def _own_names(body: Sequence[ast.stmt]) -> List[str]:
    """Names a module binds at its top level itself: classes, functions, assignments."""
    names: List[str] = []
    for stmt in body:
        if isinstance(stmt, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            names.append(stmt.name)
        elif isinstance(stmt, ast.Assign):
            names.extend(t.id for t in stmt.targets if isinstance(t, ast.Name))
    return names


def _binds_at_module_level(body: Sequence[ast.stmt], name: str) -> bool:
    """Whether a module binds ``name`` at its top level in a way not followed.

    Statements under ``if`` / ``try`` / ``with`` count (they run on import);
    function and class bodies and ``if TYPE_CHECKING:`` blocks don't (a star
    import never exports what they bind).
    """
    pending: List[ast.stmt] = list(body)
    while pending:
        stmt = pending.pop()
        if isinstance(stmt, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if stmt.name == name:
                return True
            continue
        if isinstance(stmt, (ast.Import, ast.ImportFrom)):
            if any((alias.asname or alias.name).split(".")[0] == name for alias in stmt.names):
                return True
            continue
        if isinstance(stmt, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
            for target in targets:
                if any(isinstance(n, ast.Name) and n.id == name for n in ast.walk(target)):
                    return True
            continue
        if isinstance(stmt, ast.If) and _is_type_checking(stmt.test):
            pending.extend(stmt.orelse)
            continue
        for child in ast.iter_child_nodes(stmt):
            if isinstance(child, ast.stmt):
                pending.append(child)
    return False


def _is_type_checking(test: ast.expr) -> bool:
    """``TYPE_CHECKING`` or ``typing.TYPE_CHECKING``."""
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
    )


def _meta_app_label(node: ast.ClassDef) -> str | None:
    """A literal ``Meta.app_label`` in the class body, if any."""
    for stmt in node.body:
        if isinstance(stmt, ast.ClassDef) and stmt.name == "Meta":
            for item in stmt.body:
                if (
                    isinstance(item, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "app_label" for t in item.targets)
                    and isinstance(item.value, ast.Constant)
                    and isinstance(item.value.value, str)
                ):
                    return item.value.value
    return None


def _app(path: Path) -> str:
    """The Django app label of a file's app (its package name outside Django)."""
    return app_label(app_package(path))


class _Transformer(ast.NodeTransformer):
    def __init__(self, rewriter: _Rewriter):
        self.r = rewriter
        #: The classes being visited, innermost last (the referencing model).
        self.owners: List[ast.ClassDef] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST:
        self.owners.append(node)
        self.generic_visit(node)
        self.owners.pop()
        return node

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
            if django and not self.r.django:
                return node  # SQLAlchemy ForeignKey("table.column")
            if node.args:
                node.args[0] = self._string(node.args[0], django=django)
            for kw in node.keywords:
                if kw.arg in _REFERENCE_KEYWORDS:
                    kw.value = self._string(kw.value, django=django)
        return node

    def _string(self, value: ast.expr, *, django: bool) -> ast.expr:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            owner = self.owners[-1] if self.owners else None
            internal = self.r.string(value.value, django=django, owner=owner)
            if internal is not None:
                return ast.copy_location(ast.Constant(value=internal), value)
        return value

    def _annotation(self, annotation: ast.expr) -> ast.expr:
        """An annotation with its names and quoted forward references rewritten."""
        visited: ast.expr = self.visit(annotation)
        rewritten: ast.expr = _StringAnnotations(self).visit(visited)
        return rewritten


class _StringAnnotations(ast.NodeTransformer):
    """Rewrites quoted forward references (``"Address"``, ``"list[Address]"``).

    ``Literal[...]`` values and ``Annotated[...]`` metadata are text, not
    references, and stay as written.
    """

    def __init__(self, outer: _Transformer):
        self.outer = outer

    def visit_Subscript(self, node: ast.Subscript) -> ast.AST:
        kind = _call_name(node.value)
        if kind == "Literal":
            return node
        if kind == "Annotated" and isinstance(node.slice, ast.Tuple) and node.slice.elts:
            node.slice.elts[0] = self.visit(node.slice.elts[0])
            return node
        self.generic_visit(node)
        return node

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
