"""The relationships erdify draws, as a public edge model (#359).

:func:`diagram_edges` turns parsed entities into the edges every diagram
format draws: one per foreign-key column, two (or a star) through a detected
link table, and one per declared relationship between entities no
foreign-key column or link table already connects (a many-to-many one: no
link table), with both sides of a bidirectional relationship merged into
one edge. The PlantUML and Mermaid generators render these edges, and
``--format json`` lists them, so a tool built on erdify draws exactly the same
edges without re-implementing the rules.
"""

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Literal, Mapping, Tuple

from .config import EntityInfo, FieldInfo

#: What an edge stands for (:attr:`Edge.kind`).
EdgeKind = Literal["foreign_key", "link_table", "relationship"]


@dataclass(frozen=True)
class EdgeEnd:
    """One end of an edge: how many rows of that end's entity relate to one row
    of the other end's entity.

    Attributes:
        optional: The minimum is zero (else one).
        many: The maximum is many (else one).
    """

    optional: bool
    many: bool

    @property
    def right_token(self) -> str:
        """This end's crow's-foot token right of ``--``: ``||``, ``o|``, ``o{``, ``|{``."""
        return ("o" if self.optional else "|") + ("{" if self.many else "|")

    @property
    def left_token(self) -> str:
        """This end's crow's-foot token left of ``--``: ``||``, ``|o``, ``}o``, ``}|``."""
        return self.right_token[::-1].replace("{", "}")


@dataclass(frozen=True)
class Edge:
    """One relationship line of the diagram.

    The edge is drawn from ``from_entity`` to ``to_entity``; PlantUML and
    Mermaid write it ``<from> <glyph> <to> : "<label>"`` (:attr:`glyph`), with
    names and the label encoded as each format needs.

    Attributes:
        from_entity: Name of the entity the edge starts at: the one holding
            the foreign-key column, the link table's first parent or the link
            table itself, or the side of a relationship that is kept.
        to_entity: Name of the entity it ends at.
        from_end: How many ``from_entity`` rows relate to one ``to_entity`` row.
        to_end: How many ``to_entity`` rows relate to one ``from_entity`` row.
        label: The foreign-key column or relationship attribute it is labelled with.
        kind: What the edge stands for: ``"foreign_key"`` (a foreign-key
            column), ``"link_table"`` (a column of a detected link table) or
            ``"relationship"`` (a declared ORM / model relationship).
    """

    from_entity: str
    to_entity: str
    from_end: EdgeEnd
    to_end: EdgeEnd
    label: str
    kind: EdgeKind

    @property
    def glyph(self) -> str:
        """The crow's-foot glyph PlantUML and Mermaid draw, e.g. ``}o--||``."""
        return f"{self.from_end.left_token}--{self.to_end.right_token}"


def diagram_edges(entities: Mapping[str, EntityInfo]) -> List[Edge]:
    """The edges erdify draws between ``entities``, in diagram order.

    Order: one edge per foreign-key column (in entity and column order), then
    the edges through each detected link table, then the declared
    relationships. Edges that would be drawn identically appear once.

    - **Foreign keys:** from the entity holding the column to the referenced
      one. The far end is optional when the column is nullable; the near end
      is at most one when the column is unique on its own or is the table's
      only primary-key column (1:1), else many.
    - **Link tables** (:attr:`EntityInfo.is_link_table`): a binary one is
      drawn as a path through the link entity (``A ||--o{ Link``, ``Link
      }o--|| B``), a ternary or larger one as a star from each parent to the
      link entity. A link-table column unique on its own caps its side at one.
    - **Declared relationships** (:attr:`EntityInfo.relationships`), only
      between entities no foreign-key column or link table connects (a
      many-to-many one only where no link table does): both
      sides of a bidirectional relationship are merged into one edge, paired
      by ``back_populates=`` first, then guessed by cardinality and attribute
      names; the edge starts at the entity whose name sorts first.

    Args:
        entities: Parsed entities, keyed as :func:`parse_models_directory`
            returns them. Relationship targets missing from it are skipped,
            so an excluded entity leaves no dangling edge.

    Returns:
        The edges; endpoints are entity names (:attr:`EntityInfo.name`).
    """
    return _EdgeBuilder(entities).edges()


#: The cardinality a relationship's inverse side declares: a 1:N collection
#: (``many``) is mirrored by an N:1 reference (``one``), and so on.
_INVERSE_KIND = {
    "one": "many",
    "many": "one",
    "one_to_one": "one_to_one",
    "many_to_many": "many_to_many",
}

#: The end at the target for what a relationship declares about it:
#: (kind, nullable) -> end.
_TARGET_END = {
    ("one", False): EdgeEnd(optional=False, many=False),
    ("one", True): EdgeEnd(optional=True, many=False),
    ("many", False): EdgeEnd(optional=True, many=True),
    ("one_to_one", False): EdgeEnd(optional=False, many=False),
    ("many_to_many", False): EdgeEnd(optional=True, many=True),
}
#: The source end when only one side is declared: kind -> end.
_DEFAULT_SOURCE_END = {
    "one": EdgeEnd(optional=True, many=True),
    "many": EdgeEnd(optional=False, many=False),
    "one_to_one": EdgeEnd(optional=False, many=False),
    "many_to_many": EdgeEnd(optional=True, many=True),
}

_ONE = EdgeEnd(optional=False, many=False)

_Rel = Tuple[EntityInfo, str, str, str]  # (entity, target, kind, attribute)


class _EdgeBuilder:
    """Works out the edges of :func:`diagram_edges` for one set of entities."""

    def __init__(self, entities: Mapping[str, EntityInfo]):
        self.entities = entities
        #: Table name -> the entities of that table name, in entity order.
        self._by_table: Dict[str, List[EntityInfo]] = {}
        for entity in entities.values():
            self._by_table.setdefault(entity.table_name, []).append(entity)

    def edges(self) -> List[Edge]:
        """Every edge, de-duplicated by how it is drawn, in diagram order."""
        link_table_map = self._build_link_table_map()
        found: List[Edge] = []
        for entity in self.entities.values():
            if not entity.is_link_table:
                found.extend(self._direct_edges(entity))
        for link_entity in self.entities.values():
            if link_entity.is_link_table:
                found.extend(self._link_table_edges(link_entity))

        link_pairs = {frozenset(pair) for pair in link_table_map}
        found.extend(self._declared_edges(self._connected_pairs(), link_pairs))

        edges: List[Edge] = []
        seen: set[Tuple[str, str, str, str]] = set()
        for edge in found:
            key = (edge.from_entity, edge.glyph, edge.to_entity, edge.label)
            if key not in seen:
                seen.add(key)
                edges.append(edge)
        return edges

    def _name(self, key: str) -> str:
        """The name of the entity under ``key`` (a dict key may differ from the name)."""
        return self.entities[key].name if key in self.entities else key

    def _build_link_table_map(self) -> Dict[Tuple[str, str], str]:
        """Map (entity1, entity2) -> link entity name for binary many-to-many tables."""
        link_map: Dict[Tuple[str, str], str] = {}
        for entity in self.entities.values():
            if entity.is_link_table and len(entity.fields) == 2:
                fk_fields = [f for f in entity.fields if f.is_foreign_key]
                if len(fk_fields) == 2:
                    target1 = self._fk_target(entity, fk_fields[0])
                    target2 = self._fk_target(entity, fk_fields[1])
                    if target1 and target2:
                        link_map[(target1.name, target2.name)] = entity.name
                        link_map[(target2.name, target1.name)] = entity.name
        return link_map

    @staticmethod
    def _fk_ends(field: FieldInfo, sole_pk: bool = False) -> Tuple[EdgeEnd, EdgeEnd]:
        """``(child end, parent end)`` of a direct foreign-key edge.

        Each end counts that entity per one instance of the other. The child
        end is how many children a parent has: a non-unique FK allows
        zero-or-more, while a unique single-column FK caps it at zero-or-one;
        uniqueness never forces a parent to have a child, so it is never a
        mandatory one. The parent end is how many parents a child has,
        governed by FK nullability: exactly one when NOT NULL, zero-or-one
        when nullable (#216). A unique FK is thus 1:1, a non-unique one N:1.

        ``sole_pk`` marks an FK that is the entity's *only* primary-key column
        (the shared-primary-key 1:1): the key makes it unique by definition,
        so it is 1:1 too (#222). In a composite PK the FK alone is not unique
        and stays N:1, unless it is unique on its own (#331).
        """
        child = EdgeEnd(optional=True, many=not (field.is_unique or sole_pk))
        parent = EdgeEnd(optional=field.is_nullable, many=False)
        return child, parent

    def _fk_target(self, entity: EntityInfo, field: FieldInfo) -> EntityInfo | None:
        """The entity the foreign-key column ``field`` of ``entity`` references.

        ``foreign_table`` is ``table.column`` or ``schema.table.column``. With
        a schema, only the table of that name in that schema is meant (#353):
        an excluded or unscanned target draws no edge. Without one, the only table of that name; of
        several, the (first) one declared without a schema, else the one in
        ``entity``'s schema. Anything else is ambiguous: no edge.
        """
        if not field.foreign_table:
            return None
        target = field.foreign_table.rpartition(".")[0]
        candidates = self._by_table.get(target, [])
        if not candidates and "." in target:
            schema, _, table = target.rpartition(".")
            schema = schema.rpartition(".")[2]  # a database part is not compared
            # The first of several (a Python model and a SQL table of one
            # table), as before schemas counted.
            found = [e for e in self._by_table.get(table, []) if e.schema == schema]
            return found[0] if found else None
        if len(candidates) <= 1:
            return candidates[0] if candidates else None
        # Several without a schema (a Python model and a SQL table drawing the
        # same table): the first, the Python model, as before schemas counted.
        unqualified = [e for e in candidates if e.schema is None]
        if unqualified:
            return unqualified[0]
        in_schema = [e for e in candidates if e.schema == entity.schema]
        return in_schema[0] if len(in_schema) == 1 else None

    def _connected_pairs(self) -> "set[frozenset[str]]":
        """Compute entity-name pairs already connected by a foreign-key column."""
        pairs: set[frozenset[str]] = set()
        for entity in self.entities.values():
            for field in entity.fields:
                if field.is_foreign_key:
                    target = self._fk_target(entity, field)
                    if target:
                        pairs.add(frozenset((entity.name, target.name)))
        return pairs

    def _direct_edges(self, entity: EntityInfo) -> List[Edge]:
        """Edges for foreign-key columns (not through link tables)."""
        edges: List[Edge] = []
        single_pk = sum(f.is_primary_key for f in entity.fields) == 1
        for field in entity.fields:
            if field.is_foreign_key:
                target_entity = self._fk_target(entity, field)
                if target_entity:
                    child, parent = self._fk_ends(field, sole_pk=single_pk and field.is_primary_key)
                    edges.append(
                        Edge(
                            entity.name,
                            target_entity.name,
                            child,
                            parent,
                            field.name,
                            "foreign_key",
                        )
                    )
        return edges

    def _link_table_edges(self, link_entity: EntityInfo) -> List[Edge]:
        """Edges through a link table.

        A binary association table (two FKs) is drawn as the classic M:N
        pass-through path; a member that is unique on its own (#331) caps its
        side at one link row. A ternary or higher-order one (three or more
        FKs) has no single binary cardinality, so it is drawn as a star: one
        edge from each parent to the link entity (#118).
        """
        fk_fields = [f for f in link_entity.fields if f.is_foreign_key]
        if len(fk_fields) < 2:
            return []

        entities_to_link: List[Tuple[EntityInfo, str]] = []
        for fk_field in fk_fields:
            if fk_field.foreign_table:
                target = self._fk_target(link_entity, fk_field)
                if target is not None:
                    entities_to_link.append((target, fk_field.name))

        # Arity is decided by the number of FK columns, not by how many targets
        # resolved: a ternary table with one unresolved FK must still be drawn
        # as a (partial) star, never mistaken for a binary M:N (#118).
        unique = {f.name for f in fk_fields if f.is_unique}

        def link_end(fk_name: str) -> EdgeEnd:
            return EdgeEnd(optional=True, many=fk_name not in unique)

        def edge(start: str, start_end: EdgeEnd, end: str, end_end: EdgeEnd, label: str) -> Edge:
            return Edge(start, end, start_end, end_end, label, "link_table")

        edges: List[Edge] = []
        if len(fk_fields) == 2:
            if len(entities_to_link) == 2:
                (entity1, fk1), (entity2, fk2) = entities_to_link
                edges.append(edge(entity1.name, _ONE, link_entity.name, link_end(fk1), fk1))
                edges.append(edge(link_entity.name, link_end(fk2), entity2.name, _ONE, fk2))
        else:  # three or more FK columns -> star of edges from each parent
            for parent, fk_name in entities_to_link:
                edges.append(edge(parent.name, _ONE, link_entity.name, link_end(fk_name), fk_name))
        return edges

    @staticmethod
    def _snake_case(name: str) -> str:
        """``OrderItem`` -> ``order_item``, ``HTTPRequest`` -> ``http_request``.

        The usual attribute name for a reference to a class; an acronym stays
        one word.
        """
        return re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", "_", name).lower()

    @staticmethod
    def _end(entity: EntityInfo, kind: str, attr: str) -> EdgeEnd:
        """The target end of ``entity.attr``; only a ``one`` reference can be optional."""
        if kind not in _DEFAULT_SOURCE_END:
            kind = "one"
        nullable = kind == "one" and attr in entity.nullable_relationships  # #223
        return _TARGET_END[(kind, nullable)]

    def _declared_edge(self, entity: EntityInfo, target: str, rel_type: str, attr: str) -> Edge:
        """The edge for one declared relationship of ``entity``, other side undeclared."""
        source = _DEFAULT_SOURCE_END.get(rel_type, _DEFAULT_SOURCE_END["one"])
        target_end = self._end(entity, rel_type, attr)
        return Edge(entity.name, self._name(target), source, target_end, attr, "relationship")

    def _declared_edges(
        self, fk_pairs: "set[frozenset[str]]", link_pairs: "set[frozenset[str]]"
    ) -> List[Edge]:
        """Edges for declared relationships between pairs no column already connects.

        A pair joined by a foreign-key column (``fk_pairs``) or a link table
        (``link_pairs``) already has its edge, which an ORM relationship such
        as ``relationship()`` merely mirrors. A many-to-many never mirrors a
        foreign-key column, so only a link table suppresses it: e.g. a Django
        ``ManyToManyField`` to the parent of a multi-table child (#233).

        Every declared attribute gets its own edge (#230), except that the two
        sides of a bidirectional relationship (e.g. ``User.posts`` and
        ``Post.user``) describe one edge (:meth:`_pair_sides`). That edge is
        drawn from the side whose entity name sorts first, so it does not
        depend on file order, and each end shows what its own side declares
        (#239): ``list[B]`` on ``A`` and ``list[A]`` on ``B`` give ``}o--o{``.
        """
        connected = fk_pairs | link_pairs
        rels: List[_Rel] = [
            (entity, target, rel_type, attr)
            for entity in self.entities.values()
            for target, rel_type, attr in entity.relationships
            if target in self.entities
            and frozenset((entity.name, target))
            not in (link_pairs if rel_type == "many_to_many" else connected)
        ]
        by_pair: Dict[frozenset[str], List[int]] = {}
        for i, (entity, target, _, _) in enumerate(rels):
            by_pair.setdefault(frozenset((entity.name, target)), []).append(i)
        partner: Dict[int, int] = {}
        for indices in by_pair.values():
            partner.update(self._pair_sides(rels, indices))
        folded = set(partner.values())
        edges: List[Edge] = []
        for i, (entity, target, rel_type, attr) in enumerate(rels):
            if i in folded:
                continue
            if i in partner:
                edges.append(self._merged_edge(rels[i], rels[partner[i]]))
            else:
                edges.append(self._declared_edge(entity, target, rel_type, attr))
        return edges

    def _pair_sides(self, rels: List[_Rel], indices: List[int]) -> Dict[int, int]:
        """Pair the relationships between one pair of entities: kept index -> folded index.

        1. **Explicit** (#240): a side naming its inverse (``back_populates=``)
           pairs with that attribute of the other side, mutual declarations
           first. One naming an attribute the other side does not declare is
           guessed like the rest.
        2. **Guessed**: each relationship of the first side (the entity whose
           name sorts first) folds at most one relationship declared back
           from the other side, best candidates first: the inverse
           cardinality (``many`` for ``one`` and vice versa) with attributes
           named after the class they point at on both sides (``Post.user`` /
           ``User.posts``), then on one side, then any inverse cardinality,
           then (not for a self-reference) anything left.

        Equal candidates are tried in declaration order within each entity, the
        first side before the other, so the file (entity) order never changes
        the result. The kept side is the first side's relationship; for a
        self-reference, the attribute whose name sorts first. A self-reference
        only folds an N:1 / 1:N inverse (``parent`` / ``children``): two
        references of the same cardinality
        (``friends`` / ``blocked``, both M:N) stay two edges.
        """

        def attr(i: int) -> str:
            return rels[i][3]

        def inverse_of(i: int) -> str | None:
            return rels[i][0].inverse_relationships.get(attr(i))

        def by_attr(idx: Iterable[int]) -> List[int]:
            return sorted(idx, key=attr)

        names = sorted({rels[i][0].name for i in indices} | {rels[i][1] for i in indices})
        first = names[0]
        self_ref = len(names) == 1
        side_a = {i for i in indices if rels[i][0].name == first}
        side_b = side_a if self_ref else set(indices) - side_a
        pairs: Dict[int, int] = {}
        used: set[int] = set()

        def other_side(i: int) -> "set[int]":
            return side_b if i in side_a else side_a

        def pair(i: int, j: int) -> None:
            if self_ref:
                keep, fold = by_attr((i, j))
            else:
                keep, fold = (i, j) if i in side_a else (j, i)
            pairs[keep] = fold
            used.update((i, j))

        # 1. Explicit: mutual back_populates first, then one-sided ones.
        for mutual in (True, False):
            for i in [*sorted(side_a), *sorted(side_b - side_a)]:
                inverse = inverse_of(i)
                if i in used or inverse is None:
                    continue
                j = next(
                    (
                        j
                        for j in sorted(other_side(i))
                        if j != i
                        and j not in used
                        and attr(j) == inverse
                        and (inverse_of(j) == attr(i) if mutual else inverse_of(j) is None)
                    ),
                    None,
                )
                if j is not None:
                    pair(i, j)

        # 2. Guessed: everything not paired whose inverse (if named) does not exist.
        def guessable(i: int) -> bool:
            inverse = inverse_of(i)
            return i not in used and (
                inverse is None or not any(attr(j) == inverse for j in other_side(i))
            )

        plural_names = {name: self._class_attr_names(name) for name in names}

        def exact(i: int, j: int) -> bool:
            return rels[j][2] == _INVERSE_KIND[rels[i][2]]

        def named(i: int, j: int) -> int:
            entity_i, target_i, _, attr_i = rels[i]
            return int(attr_i in plural_names[target_i]) + int(
                attr(j) in plural_names[entity_i.name]
            )

        tiers = [
            lambda i, j: exact(i, j) and named(i, j) == 2,
            lambda i, j: exact(i, j) and named(i, j) == 1,
            exact,
        ]
        if not self_ref:
            tiers.append(lambda i, j: True)
        free_a = [i for i in sorted(side_a) if guessable(i)]
        free_b = [j for j in sorted(side_b) if guessable(j)]
        for fits in tiers:
            for i in free_a:
                if i in used:
                    continue
                if self_ref and _INVERSE_KIND[rels[i][2]] == rels[i][2]:
                    continue  # two M:N / 1:1 self-references are two relationships
                j = next((j for j in free_b if j not in used and j != i and fits(i, j)), None)
                if j is not None:
                    pair(i, j)
        return pairs

    def _class_attr_names(self, name: str) -> "set[str]":
        """Attribute names that refer to class ``name``: ``user``, ``users``, ``categories``."""
        snake = self._snake_case(name)
        names = {snake, snake + "s"}
        if snake.endswith("y") and snake[-2:-1] not in ("a", "e", "i", "o", "u", ""):
            names.add(snake[:-1] + "ies")
        elif snake.endswith(("s", "x", "z", "ch", "sh")):
            names.add(snake + "es")
        return names

    def _merged_edge(self, kept: _Rel, folded: _Rel) -> Edge:
        """One edge for both sides of a relationship; each end from its own side (#239)."""
        entity, target, kind, attr = kept
        other, _, other_kind, other_attr = folded
        from_end = self._end(other, other_kind, other_attr)
        to_end = self._end(entity, kind, attr)
        return Edge(entity.name, self._name(target), from_end, to_end, attr, "relationship")
