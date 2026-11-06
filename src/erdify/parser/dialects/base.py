"""The interface every model framework ("dialect") implements, and its context."""

import ast
from dataclasses import dataclass, field
from typing import Callable, ClassVar, Dict, List, Set, Tuple

from ...config import EntityInfo, FieldInfo
from ..common import _ClassMembers, _Rel
from ..inheritance import ClassIndex, merge_members, reorder


@dataclass
class ParseContext:
    """What a dialect may read besides the class it is parsing.

    Attributes:
        classes: Every class definition in the scanned files.
        infer_keys: Infer keys for keyless sources (``--infer-keys``).
        django_raw_types: Keep Django field names (``--django-raw-types``).
        base_classes: Extra base-class names treated as Pydantic models.
        classify: The model kind of any class, or None (all dialects, in
            ``MODEL_SOURCES`` order), regardless of ``--sources``.
    """

    classes: ClassIndex = field(default_factory=lambda: ClassIndex({}))
    infer_keys: bool = False
    django_raw_types: bool = False
    base_classes: Set[str] = field(default_factory=set)
    classify: Callable[[ast.ClassDef], str | None] = lambda _node: None


class Dialect:
    """How one model framework is detected and how its class bodies are read.

    The dialect of an entity is chosen from the concrete class, and the same
    dialect reads every ancestor of it (a mixin is read the way the model that
    inherits it is). Merging the ancestors follows the MRO and is shared
    (:mod:`..inheritance`); a dialect only adjusts it through the hooks below.
    One instance lives for one parse run, so per-run caches belong on it.

    Args:
        ctx: The shared parse context.
    """

    #: The model kind this dialect produces (one of ``MODEL_SOURCES``).
    kind: ClassVar[str]

    def __init__(self, ctx: ParseContext):
        self.ctx = ctx
        self.classes = ctx.classes

    def detect(self, class_node: ast.ClassDef) -> bool:
        """Whether the class belongs to this framework."""
        raise NotImplementedError

    def is_drawable(self, class_node: ast.ClassDef) -> bool:
        """Whether a detected class becomes an entity (not, e.g., an abstract base).

        A detected class that is not drawable belongs to no other framework either.
        """
        return True

    def table_name(self, class_node: ast.ClassDef) -> str | None:
        """The table name the class declares, if any; ``__tablename__`` by default."""
        table_name = None
        for node in class_node.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.target.id == "__tablename__" and isinstance(node.value, ast.Constant):
                    table_name = str(node.value.value)
            elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "__tablename__":
                        table_name = str(node.value.value)
        return table_name

    def class_fields(
        self, class_node: ast.ClassDef, concrete: str
    ) -> Tuple[Dict[str, FieldInfo], Dict[str, _Rel]]:
        """The fields and relationships a single class body declares.

        ``concrete`` is the model a ``"self"`` reference in this body points at.
        """
        raise NotImplementedError

    def declared_names(self, class_node: ast.ClassDef) -> List[str]:
        """Attribute names a class body declares, shadowing inherited ones.

        Every annotated attribute shadows an inherited one, also when it yields
        neither a field nor a relationship (e.g. a relationship() whose
        annotation names no single class, or link_model=).
        """
        return [
            node.target.id
            for node in class_node.body
            if isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and not node.target.id.startswith("_")
        ]

    def self_owner(self, name: str, merge_order: List[str]) -> str:
        """The model a ``"self"`` reference declared in class ``name`` points at."""
        return name

    def class_members(self, class_node: ast.ClassDef, concrete: str) -> _ClassMembers:
        """A single class body's fields, relationships, and declared attribute names."""
        fields, rels = self.class_fields(class_node, concrete)
        return fields, rels, self.declared_names(class_node)

    def merge(
        self,
        class_node: ast.ClassDef,
        merge_order: List[str],
        members: Dict[str, _ClassMembers],
    ) -> Tuple[Dict[str, FieldInfo], Dict[str, _Rel]]:
        """Merge the members of the class and its ancestors; later classes win."""
        return merge_members(merge_order, members, self.kind)

    def collect(self, class_node: ast.ClassDef) -> Tuple[Dict[str, FieldInfo], Dict[str, _Rel]]:
        """Collect the fields and relationships of a class and all its ancestors.

        Which declaration of an attribute wins follows the MRO
        (:meth:`ClassIndex.merge_order`), or a dialect's own :meth:`merge`. The
        order they are listed in is the one the pre-MRO merge produced
        (:meth:`ClassIndex.listing_order`), so resolving by MRO does not
        reorder the output.
        """
        dfs_order = self.classes.dfs_order(class_node, set())
        merge_order = self.classes.merge_order(class_node)
        members = {
            name: self.class_members(self.classes.all[name], self.self_owner(name, merge_order))
            for name in dfs_order
        }
        order_fields, order_rels = self.classes.listing_order(class_node, set(), members, self.kind)
        fields, rels = self.merge(class_node, merge_order, members)
        return reorder(fields, order_fields), reorder(rels, order_rels)

    def finish(self, entity: EntityInfo, class_node: ast.ClassDef) -> None:
        """Adjust the built entity (e.g. uniqueness, implicit keys). No-op by default."""
