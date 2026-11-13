"""ERD diagram generators (PlantUML, Mermaid, JSON and an HTML preview)."""

import html
import json
import re
from typing import Dict, Iterable, List, Tuple

from .config import EntityInfo, EnumInfo, FieldInfo, is_sole_primary_key

#: Pinned Mermaid CDN major version used by the HTML preview format.
MERMAID_CDN = "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"

#: Version of the ``--format json`` document shape. Adding keys does not bump it;
#: removing or renaming a key, or changing a value's type or meaning, does.
JSON_SCHEMA_VERSION = 1


class _ERGenerator:
    """Shared ERD model: entity/enum bookkeeping and relationship resolution.

    Relationship lines use crow's-foot tokens (``}o--||``, ``||--o{``, ``||--||``,
    ``}o--o{``) that are valid in *both* PlantUML and Mermaid, so subclasses share
    the relationship logic and only differ in entity/enum block formatting.
    """

    #: The cardinality a relationship's inverse side declares: a 1:N collection
    #: (``many``) is mirrored by an N:1 reference (``one``), and so on.
    _INVERSE_KIND = {
        "one": "many",
        "many": "one",
        "one_to_one": "one_to_one",
        "many_to_many": "many_to_many",
    }

    def __init__(
        self,
        entities: Dict[str, EntityInfo],
        enums: Dict[str, EnumInfo] | None = None,
        *,
        title: str = "Database ERD",
        include_relationships: bool = True,
    ):
        self.entities = entities
        self.enums = enums or {}
        self.title = title
        self.include_relationships = include_relationships
        self._ids: Dict[Tuple[str, str], str] | None = None

    # -- Names in the diagram source (#288) ---------------------------------
    #
    # Entity and enum names come from the model source, and a SQL table can be
    # called anything (``"Order Items"``). Each format turns a name into an
    # identifier its grammar accepts (``_identifier``, made unique across
    # entities and enums) and writes references to it (``_render_ref``) and
    # quoted labels (``_label``) its own way. The IR and JSON keep real names.

    def _identifier(self, name: str) -> str:
        """The bare diagram identifier for an entity or enum ``name``."""
        return name

    def _render_ref(self, identifier: str) -> str:
        """How a reference to ``identifier`` is written (e.g. quoted)."""
        return identifier

    def _label(self, text: str) -> str:
        """A quoted relationship label."""
        return f'"{text}"'

    def _diagram_ids(self) -> Dict[Tuple[str, str], str]:
        """``("entity" | "enum", name)`` -> unique diagram identifier.

        A name the format accepts as it is keeps it; an encoded name that
        collides with another one gets a ``_2``, ``_3``, ... suffix. Entities
        are numbered before enums, each in diagram order. Keyed by
        ``EntityInfo.name`` / ``EnumInfo.name`` (:meth:`_ref` resolves a dict
        key first); built once per :meth:`generate` call.
        """
        if self._ids is None:
            entity_names = [e.name for e in self.entities.values()]
            enum_names = [self.enums[n].name for n in sorted(self._get_used_enums())]
            keys = [("entity", name) for name in dict.fromkeys(entity_names)]
            keys += [("enum", name) for name in dict.fromkeys(enum_names)]
            encoded = {key: self._identifier(key[1]) for key in keys}
            ids: Dict[Tuple[str, str], str] = {}
            taken: set[str] = set()
            for key in keys:
                if encoded[key] == key[1] and key[1] not in taken:
                    ids[key] = key[1]
                    taken.add(key[1])
            for key in keys:
                if key in ids:
                    continue
                candidate, n = encoded[key], 2
                while candidate in taken:
                    candidate, n = f"{encoded[key]}_{n}", n + 1
                ids[key] = candidate
                taken.add(candidate)
            self._ids = ids
        return self._ids

    def _ref(self, entity_name: str, kind: str = "entity") -> str:
        """The diagram reference to an entity (or enum) called ``entity_name``.

        ``entity_name`` may also be a key of ``entities`` / ``enums`` (a
        relationship target), which a caller's dict may hold apart from the name.
        """
        index = self.entities if kind == "entity" else self.enums
        if entity_name in index:
            entity_name = index[entity_name].name
        return self._render_ref(self._diagram_ids()[(kind, entity_name)])

    def _edge(self, left: str, glyph: str, right: str, label: str) -> str:
        """One relationship line between the entities ``left`` and ``right``."""
        return f"{self._ref(left)} {glyph} {self._ref(right)} : {self._label(label)}"

    def _get_used_enums(self) -> "set[str]":
        """Get set of enum names used by entity fields."""
        used_enums: set[str] = set()
        for entity in self.entities.values():
            for field in entity.fields:
                type_name = field.type_str.split(".")[-1]
                if type_name in self.enums:
                    used_enums.add(type_name)
        return used_enums

    def _build_link_table_map(self) -> Dict[Tuple[str, str], str]:
        """Build a map of (table1, table2) -> link_table_name for many-to-many."""
        link_map: Dict[Tuple[str, str], str] = {}

        for entity in self.entities.values():
            if entity.is_link_table and len(entity.fields) == 2:
                fk_fields = [f for f in entity.fields if f.is_foreign_key]
                if len(fk_fields) == 2:
                    table1 = (
                        fk_fields[0].foreign_table.split(".")[0]
                        if fk_fields[0].foreign_table
                        else None
                    )
                    table2 = (
                        fk_fields[1].foreign_table.split(".")[0]
                        if fk_fields[1].foreign_table
                        else None
                    )

                    if table1 and table2:
                        link_map[(table1, table2)] = entity.name
                        link_map[(table2, table1)] = entity.name

        return link_map

    @staticmethod
    def _fk_glyph(field: FieldInfo, sole_pk: bool = False) -> str:
        """Crow's-foot glyph for a direct FK edge, written ``child ... parent``.

        Each end counts that entity per one instance of the other. The child
        end (left) is how many children a parent has: a non-unique FK allows
        zero-or-more (``}o``), while a unique single-column FK caps it at
        zero-or-one (``|o``) — uniqueness limits it to at most one, but never
        forces a parent to have a child, so it is never a mandatory ``||``.
        The parent end (right) is how many parents a child has, governed by FK
        nullability: exactly one (``||``) when NOT NULL, zero-or-one (``o|``)
        when nullable (#216). A unique FK is thus rendered 1:1 (``|o--||`` /
        ``|o--o|``), a non-unique one N:1 (``}o--||`` / ``}o--o|``).

        ``sole_pk`` marks an FK that is the entity's *only* primary-key column
        (the shared-primary-key 1:1): the key makes it unique by definition, so
        it is drawn 1:1 too (#222). In a composite PK the FK alone is not
        unique and stays N:1, unless it is unique on its own (#331).
        """
        child = "|o" if field.is_unique or sole_pk else "}o"
        parent = "o|" if field.is_nullable else "||"
        return f"{child}--{parent}"

    def _entity_by_table(self, table_name: str) -> EntityInfo | None:
        """Find an entity by its table name."""
        for entity in self.entities.values():
            if entity.table_name == table_name:
                return entity
        return None

    def _connected_pairs(self) -> "set[frozenset[str]]":
        """Compute entity-name pairs already connected by a foreign-key line."""
        pairs: set[frozenset[str]] = set()
        for entity in self.entities.values():
            for field in entity.fields:
                if field.is_foreign_key and field.foreign_table:
                    target = self._entity_by_table(field.foreign_table.split(".")[0])
                    if target:
                        pairs.add(frozenset((entity.name, target.name)))
        return pairs

    def _generate_direct_relationships(
        self, entity: EntityInfo, link_table_map: Dict[Tuple[str, str], str]
    ) -> List[str]:
        """Generate direct relationships (foreign keys without link tables)."""
        lines: List[str] = []
        single_pk = sum(f.is_primary_key for f in entity.fields) == 1
        for field in entity.fields:
            if field.is_foreign_key and field.foreign_table:
                target_table = field.foreign_table.split(".")[0]
                target_entity = None
                for e in self.entities.values():
                    if e.table_name == target_table:
                        target_entity = e
                        break
                if target_entity:
                    glyph = self._fk_glyph(field, sole_pk=single_pk and field.is_primary_key)
                    lines.append(self._edge(entity.name, glyph, target_entity.name, field.name))
        return lines

    def _generate_link_table_relationships(self, link_entity: EntityInfo) -> List[str]:
        """Generate relationships through a link table.

        A binary association table (two FKs) is drawn as the classic M:N
        pass-through path; a member that is unique on its own (#331) caps its
        side at one link row (``||--o|`` / ``|o--||``). A ternary or
        higher-order one (three or more FKs) has no single binary cardinality,
        so it is drawn as a star: one edge from each parent to the link
        entity (#118).
        """
        lines: List[str] = []
        fk_fields = [f for f in link_entity.fields if f.is_foreign_key]
        if len(fk_fields) < 2:
            return lines

        entities_to_link: List[Tuple[EntityInfo, str]] = []
        for fk_field in fk_fields:
            if fk_field.foreign_table:
                target_table = fk_field.foreign_table.split(".")[0]
                for e in self.entities.values():
                    if e.table_name == target_table:
                        entities_to_link.append((e, fk_field.name))
                        break

        # Arity is decided by the number of FK columns, not by how many targets
        # resolved: a ternary table with one unresolved FK must still be drawn
        # as a (partial) star, never mistaken for a binary M:N (#118).
        # A member that is unique on its own (#331) gives each parent at most
        # one link row.
        unique = {f.name for f in fk_fields if f.is_unique}
        if len(fk_fields) == 2:
            if len(entities_to_link) == 2:
                entity1, fk1_name = entities_to_link[0]
                entity2, fk2_name = entities_to_link[1]
                many1 = "o|" if fk1_name in unique else "o{"
                many2 = "|o" if fk2_name in unique else "}o"
                lines.append(self._edge(entity1.name, f"||--{many1}", link_entity.name, fk1_name))
                lines.append(self._edge(link_entity.name, f"{many2}--||", entity2.name, fk2_name))
        else:  # three or more FK columns -> star of edges from each parent
            for parent, fk_name in entities_to_link:
                many = "o|" if fk_name in unique else "o{"
                lines.append(self._edge(parent.name, f"||--{many}", link_entity.name, fk_name))

        return lines

    @staticmethod
    def _snake_case(name: str) -> str:
        """``OrderItem`` -> ``order_item``, ``HTTPRequest`` -> ``http_request``.

        The usual attribute name for a reference to a class; an acronym stays
        one word.
        """
        return re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", "_", name).lower()

    #: Crow's-foot end at the target for what a relationship declares about
    #: it: (kind, nullable) -> token, written on the target's side.
    _TARGET_END = {
        ("one", False): "||",
        ("one", True): "o|",
        ("many", False): "o{",
        ("one_to_one", False): "||",
        ("many_to_many", False): "o{",
    }
    #: The source end when only one side is declared: kind -> token.
    _DEFAULT_SOURCE_END = {"one": "}o", "many": "||", "one_to_one": "||", "many_to_many": "}o"}

    @staticmethod
    def _mirror(token: str) -> str:
        """The same end written on the other side of ``--`` (``o{`` -> ``}o``)."""
        return token[::-1].replace("{", "}")

    def _end(self, entity: EntityInfo, kind: str, attr: str) -> str:
        """The target end of ``entity.attr``; only a ``one`` reference can be optional."""
        if kind not in self._DEFAULT_SOURCE_END:
            kind = "one"
        nullable = kind == "one" and attr in entity.nullable_relationships  # #223
        return self._TARGET_END[(kind, nullable)]

    def _declared_line(self, entity: EntityInfo, target: str, rel_type: str, attr: str) -> str:
        """The edge for one declared relationship of ``entity``, other side undeclared."""
        source = self._DEFAULT_SOURCE_END.get(rel_type, self._DEFAULT_SOURCE_END["one"])
        glyph = f"{source}--{self._end(entity, rel_type, attr)}"
        return self._edge(entity.name, glyph, target, attr)

    def _declared_relationship_lines(
        self, fk_pairs: "set[frozenset[str]]", link_pairs: "set[frozenset[str]]"
    ) -> List[str]:
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
        rels = [
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
        lines: List[str] = []
        for i, (entity, target, rel_type, attr) in enumerate(rels):
            if i in folded:
                continue
            if i in partner:
                lines.append(self._merged_line(rels[i], rels[partner[i]]))
            else:
                lines.append(self._declared_line(entity, target, rel_type, attr))
        return lines

    def _pair_sides(
        self, rels: "List[Tuple[EntityInfo, str, str, str]]", indices: List[int]
    ) -> Dict[int, int]:
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
            return rels[j][2] == self._INVERSE_KIND[rels[i][2]]

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
                if self_ref and self._INVERSE_KIND[rels[i][2]] == rels[i][2]:
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

    def _merged_line(
        self,
        kept: "Tuple[EntityInfo, str, str, str]",
        folded: "Tuple[EntityInfo, str, str, str]",
    ) -> str:
        """One edge for both sides of a relationship; each end from its own side (#239)."""
        entity, target, kind, attr = kept
        other, _, other_kind, other_attr = folded
        left = self._mirror(self._end(other, other_kind, other_attr))
        right = self._end(entity, kind, attr)
        return self._edge(entity.name, f"{left}--{right}", target, attr)

    def _relationship_lines(self) -> List[str]:
        """Resolve every relationship line, de-duplicated and ordered.

        Order: direct foreign-key edges, then many-to-many through link tables,
        then declared relationships for pairs not already connected (so keyless
        models get edges without duplicating SQLModel/SQLAlchemy foreign keys).
        Empty when the generator was built with ``include_relationships=False``
        (``--no-relationships``, #232).
        """
        if not self.include_relationships:
            return []
        link_table_map = self._build_link_table_map()
        lines: List[str] = []
        seen: set[str] = set()

        for entity in self.entities.values():
            if not entity.is_link_table:
                for rel in self._generate_direct_relationships(entity, link_table_map):
                    if rel not in seen:
                        lines.append(rel)
                        seen.add(rel)

        for link_entity in self.entities.values():
            if link_entity.is_link_table:
                for rel in self._generate_link_table_relationships(link_entity):
                    if rel not in seen:
                        lines.append(rel)
                        seen.add(rel)

        link_pairs: set[frozenset[str]] = set()
        for table_a, table_b in link_table_map:
            entity_a = self._entity_by_table(table_a)
            entity_b = self._entity_by_table(table_b)
            if entity_a and entity_b:
                link_pairs.add(frozenset((entity_a.name, entity_b.name)))

        for rel in self._declared_relationship_lines(self._connected_pairs(), link_pairs):
            if rel not in seen:
                lines.append(rel)
                seen.add(rel)

        return lines


class PlantUMLGenerator(_ERGenerator):
    """Generates a PlantUML ERD diagram from entities.

    Public API: the constructor and :meth:`generate`.

    Args:
        entities: Entity name to EntityInfo, as returned by the parsers.
        enums: Optional enum name to EnumInfo.
        title: Diagram title.
        include_relationships: Draw relationship lines (``False`` omits the
            whole ``' Relationships`` section).
    """

    def _identifier(self, name: str) -> str:
        """One word: other characters become ``_`` (``Order Items`` -> ``Order_Items``)."""
        return re.sub(r"\W+", "_", name) or "_"

    @staticmethod
    def _text(text: str) -> str:
        """Text on one line: ``"`` and ``<`` (markup) as ``&#34;`` / ``&#60;``.

        A control character (line break) becomes a space.
        """
        text = re.sub(r"[\x00-\x1f\x7f]", " ", text)
        return text.replace('"', "&#34;").replace("<", "&#60;")

    def _label(self, text: str) -> str:
        """A quoted relationship label."""
        return f'"{self._text(text)}"'

    def generate(self) -> str:
        """Render the diagram.

        Returns:
            PlantUML source, from ``@startuml`` to ``@enduml``.
        """
        self._ids = None  # the entities may have changed since the last call
        lines = [
            f"@startuml {self.title}",
            '!define Table(name,desc) class name as "desc" << (T,#FFAAAA) >>',
            "!define primary_key(x) <b><color:#b8861b><&key></color> x</b>",
            "!define foreign_key(x) <color:#aaaaaa><&key></color> x",
            "!define column(x) <color:#efefef><&media-record></color> x",
            "",
            "skinparam linetype ortho",
            "skinparam roundcorner 5",
            "skinparam class {",
            "    BackgroundColor White",
            "    ArrowColor Gray",
            "    BorderColor Gray",
            "}",
            "",
        ]

        used_enums = self._get_used_enums()
        if used_enums:
            lines.append("' Enums")
            lines.append("")
            for enum_name in sorted(used_enums):
                if enum_name in self.enums:
                    lines.extend(self._generate_enum(self.enums[enum_name]))
                    lines.append("")

        lines.append("' Entities")
        lines.append("")
        for entity in self.entities.values():
            lines.extend(self._generate_entity(entity))
            lines.append("")

        if self.include_relationships:
            lines.append("' Relationships")
            lines.append("")
            lines.extend(self._relationship_lines())
            lines.append("")

        lines.append("@enduml")

        return "\n".join(lines)

    def _generate_entity(self, entity: EntityInfo) -> List[str]:
        """Generate PlantUML entity definition."""
        lines = []
        head = f'entity "{self._text(entity.table_name)}" as {self._ref(entity.name)}'
        if entity.is_link_table:
            lines.append(f"{head} << (L, #AAFFAA) link >> {{")
        else:
            lines.append(f"{head} {{")

        if entity.fields:
            for field in entity.fields:
                lines.append(f"  {self._format_field(field, entity.fields)}")
        else:
            lines.append("  ' (no fields)")

        lines.append("}")
        return lines

    def _generate_enum(self, enum_info: EnumInfo) -> List[str]:
        """Generate PlantUML enum definition."""
        alias = self._ref(enum_info.name, "enum")
        head = alias if alias == enum_info.name else f'"{self._text(enum_info.name)}" as {alias}'
        lines = [f"enum {head} << (E,#FFCC00) >> {{"]
        for value in enum_info.values:
            lines.append(f"  {self._text(value)}")
        lines.append("}")
        return lines

    def _format_field(self, field: FieldInfo, fields: List[FieldInfo]) -> str:
        """Format a field for PlantUML; ``fields`` are the entity's columns."""
        if field.is_primary_key:
            prefix = "primary_key"
        elif field.is_foreign_key:
            prefix = "foreign_key"
        else:
            prefix = "column"

        type_str = field.type_str.split(".")[-1]
        nullable = "?" if field.is_nullable else ""

        default = ""
        if field.default_value is not None:
            default_val = field.default_value
            if "." in default_val:
                default_val = default_val.split(".")[-1]
            default = f" = {self._text(default_val)}"

        # A sole primary key is unique by being the key; a composite member
        # that is unique on its own shows UK (#331).
        unique = " UK" if field.is_unique and not is_sole_primary_key(field, fields) else ""
        name = self._text(field.name)
        if name != field.name or any(c in name for c in ",()"):
            # A macro argument: quoted, it may hold a comma or parenthesis.
            name = f'"{name}"'

        # Omit the type suffix entirely when the type is unknown (e.g. an
        # untyped Core Column on a synthesized link table) to avoid a dangling ":".
        if not type_str:
            return f"{prefix}({name}){unique}"

        return f"{prefix}({name}) : {type_str}{nullable}{default}{unique}"


class MermaidGenerator(_ERGenerator):
    """Generates a Mermaid ``erDiagram`` from entities.

    Public API: the constructor and :meth:`generate`.

    Args:
        entities: Entity name to EntityInfo, as returned by the parsers.
        enums: Optional enum name to EnumInfo.
        title: Accepted for a uniform API; Mermaid ``erDiagram`` has no title.
        include_relationships: Draw relationship lines.
    """

    # The grammar these mirror is Mermaid 11's ``erDiagram`` lexer. Its
    # character classes are ASCII plus everything from U+00C0 (attributes) or
    # U+0080 (entities) up, and its ``\b`` is ASCII-only, hence ``_NOT_WORD``.
    _NOT_WORD = r"(?![0-9A-Za-z_])"
    #: An entity name Mermaid reads unquoted ...
    _BARE_ENTITY = re.compile(r"[0-9A-Za-z_\u0080-\U0010ffff][-0-9A-Za-z_\u0080-\U0010ffff]*")
    #: ... unless it starts with a keyword (``one``, ``to``, ``class``, ...).
    _ENTITY_KEYWORD = re.compile(
        r"(?:erdiagram|style|classdef|class|one|many|to|u|1|acctitle|accdescr)" + _NOT_WORD,
        re.IGNORECASE,
    )
    #: An attribute name or type, which must not start with a key (``PK``).
    _ATTRIBUTE_CHARS = r"-*0-9A-Za-z_\[\]()\u00c0-\U0010ffff"
    _ATTRIBUTE_WORD = re.compile(rf"[*A-Za-z_\u00c0-\U0010ffff][{_ATTRIBUTE_CHARS}]*")
    _ATTRIBUTE_KEY = re.compile(r"(?:pk|fk|uk)" + _NOT_WORD, re.IGNORECASE)
    #: Characters quoted text writes as Mermaid entity codes, which it decodes
    #: when drawing: a quote or ``%`` / backslash (not allowed in a quoted
    #: entity name), markup, ``#`` (starts a code) and ``~`` (a generic type
    #: inside an entity block, even within quotes).
    _CODES = {
        "#": "#35;",
        '"': "#quot;",
        "%": "#37;",
        "\\": "#92;",
        "&": "#38;",
        "<": "#lt;",
        ">": "#gt;",
        "~": "#126;",
    }
    #: A layout statement Mermaid finds even in a quoted entity name; written
    #: as codes in all quoted text, which draws the same.
    _DIRECTION = re.compile(r"(direction)(\s+)(?=(?:tb|bt|rl|lr))", re.IGNORECASE)

    def _identifier(self, name: str) -> str:
        """The entity name as quoted text (:meth:`_text`)."""
        return self._text(name) or "_"

    def _render_ref(self, identifier: str) -> str:
        """Unquoted when Mermaid reads the name as one word, quoted otherwise."""
        if self._BARE_ENTITY.fullmatch(identifier) and not self._ENTITY_KEYWORD.match(identifier):
            return identifier
        return f'"{identifier}"'

    def _label(self, text: str) -> str:
        """A quoted relationship label."""
        return f'"{self._text(text)}"'

    @classmethod
    def _text(cls, text: str) -> str:
        """Text for inside double quotes, drawn as it is: ``R&D "x"`` -> ``R#38;D #quot;x#quot;``.

        A control character (line break) becomes a space, and each space in
        ``direction TB`` (``LR``, ...) the code ``#32;``.
        """
        text = re.sub(r"[\x00-\x1f\x7f]", " ", text)
        text = "".join(cls._CODES.get(c, c) for c in text)
        return cls._DIRECTION.sub(lambda m: m.group(1) + "#32;" * len(m.group(2)), text)

    @classmethod
    def _attribute_word(cls, name: str) -> str:
        """``name`` as an attribute word: ``Author Key`` -> ``Author_Key``, ``1st`` -> ``_1st``.

        Characters Mermaid doesn't allow become ``_``; a name starting with a
        digit or hyphen, or with a key (``pk``), gets a leading ``_``.
        """
        if cls._ATTRIBUTE_WORD.fullmatch(name) and not cls._ATTRIBUTE_KEY.match(name):
            return name
        word = re.sub(rf"[^{cls._ATTRIBUTE_CHARS}]+", "_", name)
        if not cls._ATTRIBUTE_WORD.fullmatch(word) or cls._ATTRIBUTE_KEY.match(word):
            word = "_" + word
        return word

    def generate(self) -> str:
        """Render the diagram.

        Returns:
            Mermaid ``erDiagram`` source.
        """
        self._ids = None  # the entities may have changed since the last call
        lines = ["erDiagram"]

        for entity in self.entities.values():
            lines.extend(self._generate_entity(entity))

        # Enums have no native Mermaid construct; render each used one as an
        # entity block listing its values so the values stay visible.
        for enum_name in sorted(self._get_used_enums()):
            if enum_name in self.enums:
                lines.extend(self._generate_enum(self.enums[enum_name]))

        for rel in self._relationship_lines():
            lines.append(f"    {rel}")

        return "\n".join(lines)

    def _generate_entity(self, entity: EntityInfo) -> List[str]:
        """Generate a Mermaid entity block."""
        lines = [f"    {self._ref(entity.name)} {{"]
        for field in entity.fields:
            lines.append(f"        {self._format_attr(field, entity.fields)}")
        lines.append("    }")
        return lines

    def _generate_enum(self, enum_info: EnumInfo) -> List[str]:
        """Render an enum as a Mermaid entity block listing its values."""
        lines = [f"    {self._ref(enum_info.name, 'enum')} {{"]
        for value in enum_info.values:
            word = self._attribute_word(value)
            comment = "" if word == value else f' "{self._text(value)}"'
            lines.append(f"        enum {word}{comment}")
        lines.append("    }")
        return lines

    def _format_attr(self, field: FieldInfo, fields: List[FieldInfo]) -> str:
        """Format a Mermaid attribute line: ``<type> <name> [keys] ["comment"]``.

        ``fields`` are the entity's columns.
        """
        type_token = self._mermaid_type(field.type_str)

        keys = []
        if field.is_primary_key:
            keys.append("PK")
        if field.is_foreign_key:
            keys.append("FK")
        if field.is_unique and not is_sole_primary_key(field, fields):  # #331
            keys.append("UK")
        key_str = ",".join(keys)

        name = self._attribute_word(field.name)
        comment_parts = [] if name == field.name else [field.name]
        if field.is_nullable:
            comment_parts.append("nullable")
        if field.default_value is not None:
            default_val = field.default_value
            if "." in default_val:
                default_val = default_val.split(".")[-1]
            comment_parts.append(f"default {default_val}")

        parts = [type_token, name]
        if key_str:
            parts.append(key_str)
        line = " ".join(parts)
        if comment_parts:
            line += f' "{self._text(", ".join(comment_parts))}"'
        return line

    @staticmethod
    def _mermaid_type(type_str: str) -> str:
        """Reduce a type to a single Mermaid-safe token.

        Mermaid attribute types must be a single token, so spaces, pipes and
        brackets (e.g. ``list[str]``) are collapsed to underscores.
        """
        cleaned = type_str.split(".")[-1]
        token = re.sub(r"[^0-9A-Za-z_]+", "_", cleaned).strip("_")
        return MermaidGenerator._attribute_word(token or "unknown")


def generate_plantuml(
    entities: Dict[str, EntityInfo],
    enums: Dict[str, EnumInfo] | None = None,
    *,
    title: str = "Database ERD",
    include_enums: bool = True,
    include_relationships: bool = True,
) -> str:
    """
    Generate a PlantUML ERD diagram from parsed entities.

    Args:
        entities: Dictionary of entity name to EntityInfo
        enums: Optional dictionary of enum name to EnumInfo
        title: Title for the diagram
        include_enums: Whether to include enum definitions
        include_relationships: Whether to include relationship lines

    Returns:
        PlantUML diagram as string
    """
    generator = PlantUMLGenerator(
        entities=entities,
        enums=enums if include_enums else None,
        title=title,
        include_relationships=include_relationships,
    )
    return generator.generate()


def generate_mermaid(
    entities: Dict[str, EntityInfo],
    enums: Dict[str, EnumInfo] | None = None,
    *,
    title: str = "Database ERD",
    include_enums: bool = True,
    include_relationships: bool = True,
) -> str:
    """
    Generate a Mermaid ``erDiagram`` from parsed entities.

    Args:
        entities: Dictionary of entity name to EntityInfo
        enums: Optional dictionary of enum name to EnumInfo
        title: Unused (Mermaid erDiagram has no title); accepted for a uniform API
        include_enums: Whether to render used enums as entity blocks
        include_relationships: Whether to include relationship lines

    Returns:
        Mermaid erDiagram as string
    """
    generator = MermaidGenerator(
        entities=entities,
        enums=enums if include_enums else None,
        title=title,
        include_relationships=include_relationships,
    )
    return generator.generate()


def generate_json(
    entities: Dict[str, EntityInfo],
    enums: Dict[str, EnumInfo] | None = None,
    *,
    title: str = "Database ERD",
    include_enums: bool = True,
    include_relationships: bool = True,
) -> str:
    """
    Serialize the parsed model as JSON (a stable, documented schema).

    Shape: ``{schema_version, title, entities: [{name, table_name, source, is_link_table,
    fields: [{name, type, primary_key, foreign_key, nullable, foreign_table,
    index, unique, default}], relationships: [{target, type, attribute, nullable,
    inverse}]}],
    enums:
    [{name, values}]}``. Downstream tools can consume this without re-parsing.
    ``schema_version`` is :data:`JSON_SCHEMA_VERSION`; consumers should ignore
    keys they do not know. The full schema is documented in
    ``docs/usage/output-formats.md`` and published as a JSON Schema,
    ``docs/schema/output-v1.json``.

    Args:
        entities: Dictionary of entity name to EntityInfo
        enums: Optional dictionary of enum name to EnumInfo
        title: Value of the ``title`` key
        include_enums: Whether to fill ``enums`` (otherwise ``[]``)
        include_relationships: Whether to fill each entity's ``relationships``
            (otherwise ``[]``)

    Returns:
        The JSON document as an indented string
    """
    model = {
        "schema_version": JSON_SCHEMA_VERSION,
        "title": title,
        "entities": [
            {
                "name": entity.name,
                "table_name": entity.table_name,
                "source": entity.source,
                "is_link_table": entity.is_link_table,
                "fields": [
                    {
                        "name": f.name,
                        "type": f.type_str,
                        "primary_key": f.is_primary_key,
                        "foreign_key": f.is_foreign_key,
                        "nullable": f.is_nullable,
                        "foreign_table": f.foreign_table,
                        "index": f.index,
                        "unique": f.is_unique,
                        "default": f.default_value,
                    }
                    for f in entity.fields
                ],
                "relationships": (
                    [
                        {
                            "target": target,
                            "type": rel_type,
                            "attribute": attr,
                            "nullable": rel_type == "one" and attr in entity.nullable_relationships,
                            "inverse": entity.inverse_relationships.get(attr),
                        }
                        for target, rel_type, attr in entity.relationships
                    ]
                    if include_relationships
                    else []
                ),
            }
            for entity in entities.values()
        ],
        "enums": (
            [{"name": e.name, "values": e.values} for e in (enums or {}).values()]
            if include_enums
            else []
        ),
    }
    return json.dumps(model, indent=2)


def generate_html(
    entities: Dict[str, EntityInfo],
    enums: Dict[str, EnumInfo] | None = None,
    *,
    title: str = "Database ERD",
    include_enums: bool = True,
    include_relationships: bool = True,
) -> str:
    """
    Render a self-contained HTML page that draws the ERD with Mermaid.

    The page loads Mermaid from a pinned CDN (``MERMAID_CDN``), so it needs
    internet access to render. Open it in a browser to view the diagram. The
    diagram source is HTML-escaped (a name may hold ``<`` or ``&``); Mermaid
    decodes it before parsing.

    Args:
        entities: Dictionary of entity name to EntityInfo
        enums: Optional dictionary of enum name to EnumInfo
        title: Page ``<title>`` and heading (HTML-escaped)
        include_enums: Whether to render used enums as entity blocks
        include_relationships: Whether to include relationship lines

    Returns:
        A complete HTML document as string
    """
    diagram = generate_mermaid(
        entities,
        enums,
        title=title,
        include_enums=include_enums,
        include_relationships=include_relationships,
    )
    safe_title = html.escape(title)
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"  <title>{safe_title}</title>\n"
        f'  <script src="{MERMAID_CDN}"></script>\n'
        "  <style>body{font-family:system-ui,sans-serif;margin:2rem;color:#222}"
        "h1{font-size:1.1rem;color:#555;font-weight:600}</style>\n"
        "</head>\n"
        "<body>\n"
        f"  <h1>{safe_title}</h1>\n"
        '  <pre class="mermaid">\n'
        f"{html.escape(diagram, quote=False)}\n"
        "  </pre>\n"
        "  <script>mermaid.initialize({ startOnLoad: true });</script>\n"
        "</body>\n"
        "</html>\n"
    )
