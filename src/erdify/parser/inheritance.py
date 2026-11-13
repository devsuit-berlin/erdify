"""Class hierarchy of the parsed files: MRO, merge order and member merging.

Shared by every dialect. A model's fields come from its own body and its
bases; which declaration wins follows Python's MRO (#228), and the order they
are listed in follows the pre-MRO recursive merge.
"""

import ast
from typing import Dict, List, Mapping, Protocol, Tuple

from ..config import FieldInfo
from .common import _V, _ClassMembers, _Rel


class RedeclarationRule(Protocol):
    """What a class body's redeclared attribute removes from what its bases stored.

    Implemented by every dialect (:class:`~.dialects.base.Dialect`); Django
    overrides the listing rule because its storage key depends on the field
    kind (and resolves the winners itself, ``DjangoDialect.merge``).
    """

    def drop_on_merge(
        self,
        fields: Dict[str, FieldInfo],
        rels: Dict[str, _Rel],
        attr: str,
        class_fields: Dict[str, FieldInfo],
        class_rels: Dict[str, _Rel],
    ) -> None:
        """Drop what earlier classes stored for ``attr`` before a later class merges in."""

    def drop_on_listing(
        self, fields: Dict[str, FieldInfo], rels: Dict[str, _Rel], attr: str
    ) -> None:
        """Drop ``attr`` in the listing-order merge so the body's position wins."""


class ClassIndex:
    """Every class definition found in the scanned files, by name.

    Args:
        classes: Class name to its definition (last definition wins).
    """

    def __init__(self, classes: Dict[str, ast.ClassDef]):
        self.all = classes
        self._mro_cache: Dict[str, List[str] | None] = {}

    def local_bases(self, class_node: ast.ClassDef) -> List[str]:
        """Names of the direct bases that are classes parsed from the input."""
        return [
            base.id
            for base in class_node.bases
            if isinstance(base, ast.Name) and base.id in self.all
        ]

    def dfs_order(self, class_node: ast.ClassDef, visited: set[str]) -> List[str]:
        """Classes in depth-first post-order: bases (left to right), then the class.

        Each class appears once. This is the order fields are listed in.
        """
        if class_node.name in visited:
            return []
        visited.add(class_node.name)
        order: List[str] = []
        for base in self.local_bases(class_node):
            order.extend(self.dfs_order(self.all[base], visited))
        order.append(class_node.name)
        return order

    def mro(self, name: str, stack: Tuple[str, ...] = ()) -> List[str] | None:
        """C3 linearization of a parsed class, like Python's ``__mro__``.

        Bases outside the parsed files are ignored. Returns None when Python
        would reject the hierarchy (no consistent order) or it is cyclic, e.g.
        ``class User(User)`` extending a namesake.
        """
        if name in self._mro_cache:
            return self._mro_cache[name]
        if name in stack:
            return None
        bases = self.local_bases(self.all[name])
        seqs: List[List[str]] = []
        for base in bases:
            base_mro = self.mro(base, stack + (name,))
            if base_mro is None:
                self._mro_cache[name] = None
                return None
            seqs.append(base_mro)
        seqs.append(list(bases))

        result = [name]
        seqs = [seq for seq in seqs if seq]
        while seqs:
            for seq in seqs:
                head = seq[0]
                if not any(head in other[1:] for other in seqs):
                    break
            else:
                self._mro_cache[name] = None
                return None
            result.append(head)
            seqs = [[c for c in seq if c != head] for seq in seqs]
            seqs = [seq for seq in seqs if seq]
        self._mro_cache[name] = result
        return result

    def merge_order(self, class_node: ast.ClassDef) -> List[str]:
        """Classes to merge members from, where a later class overrides an earlier one.

        This is the reversed MRO, so the class body wins over its bases and an
        earlier base wins over a later one, as in Python (#228). Without a valid
        MRO it falls back to :meth:`dfs_order`.
        """
        mro = self.mro(class_node.name)
        if mro is None:
            return self.dfs_order(class_node, set())
        return mro[::-1]

    def listing_order(
        self,
        class_node: ast.ClassDef,
        visited: set[str],
        members: Dict[str, _ClassMembers],
        rule: RedeclarationRule,
    ) -> Tuple[Dict[str, FieldInfo], Dict[str, _Rel]]:
        """The keys, in listing order, of the recursive merge used before #228.

        Each base's whole subtree is merged in (left to right, each class once),
        then the class body. Only a body's own redeclaration can move an
        inherited attribute to the body's position (``rule.drop_on_listing``,
        Django only); a sibling base never displaces another sibling's
        attribute. Only the key order is used.
        """
        fields: Dict[str, FieldInfo] = {}
        rels: Dict[str, _Rel] = {}
        if class_node.name in visited:
            return fields, rels
        visited.add(class_node.name)
        for base in self.local_bases(class_node):
            base_fields, base_rels = self.listing_order(self.all[base], visited, members, rule)
            fields.update(base_fields)
            rels.update(base_rels)
        class_fields, class_rels, declared = members[class_node.name]
        for attr in declared:
            rule.drop_on_listing(fields, rels, attr)
        fields.update(class_fields)
        rels.update(class_rels)
        return fields, rels


def reorder(values: Dict[str, _V], order: Mapping[str, object]) -> Dict[str, _V]:
    """Return ``values`` with keys in ``order``'s key order, extra keys last."""
    result = {key: values[key] for key in order if key in values}
    result.update((key, value) for key, value in values.items() if key not in result)
    return result


def merge_members(
    order: List[str], members: Dict[str, _ClassMembers], rule: RedeclarationRule
) -> Tuple[Dict[str, FieldInfo], Dict[str, _Rel]]:
    """Merge class members in ``order``; a later class overrides an earlier one.

    A redeclared attribute replaces whatever an earlier class stored for it,
    even under another key or kind (``rule.drop_on_merge``): a Django
    relationship ``owner`` vs. its FK column ``owner_id`` (#224), or a column
    vs. a model reference.
    """
    fields: Dict[str, FieldInfo] = {}
    rels: Dict[str, _Rel] = {}
    for class_name in order:
        class_fields, class_rels, declared = members[class_name]
        for attr in declared:
            rule.drop_on_merge(fields, rels, attr, class_fields, class_rels)
        fields.update(class_fields)
        rels.update(class_rels)
    return fields, rels
