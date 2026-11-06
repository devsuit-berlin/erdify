"""ERD diagram generators (PlantUML, Mermaid, JSON and an HTML preview)."""

import html
import json
import re
from typing import Dict, List, Tuple

from .config import EntityInfo, EnumInfo, FieldInfo

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
        unique and stays N:1.
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
                    lines.append(f'{entity.name} {glyph} {target_entity.name} : "{field.name}"')
        return lines

    def _generate_link_table_relationships(self, link_entity: EntityInfo) -> List[str]:
        """Generate relationships through a link table.

        A binary association table (two FKs) is drawn as the classic M:N
        pass-through path. A ternary or higher-order one (three or more FKs)
        has no single binary cardinality, so it is drawn as a star: one edge
        from each parent to the link entity (#118).
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
        if len(fk_fields) == 2:
            if len(entities_to_link) == 2:
                entity1, fk1_name = entities_to_link[0]
                entity2, fk2_name = entities_to_link[1]
                lines.append(f'{entity1.name} ||--o{{ {link_entity.name} : "{fk1_name}"')
                lines.append(f'{link_entity.name} }}o--|| {entity2.name} : "{fk2_name}"')
        else:  # three or more FK columns -> star of edges from each parent
            for parent, fk_name in entities_to_link:
                lines.append(f'{parent.name} ||--o{{ {link_entity.name} : "{fk_name}"')

        return lines

    @staticmethod
    def _snake_case(name: str) -> str:
        """``OrderItem`` -> ``order_item``, ``HTTPRequest`` -> ``http_request``.

        The usual attribute name for a reference to a class; an acronym stays
        one word.
        """
        return re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", "_", name).lower()

    @staticmethod
    def _declared_line(entity: EntityInfo, target: str, rel_type: str, attr: str) -> str:
        """The edge for one declared relationship of ``entity``."""
        if rel_type == "many":
            return f'{entity.name} ||--o{{ {target} : "{attr}"'
        if rel_type == "one_to_one":
            return f'{entity.name} ||--|| {target} : "{attr}"'
        if rel_type == "many_to_many":
            return f'{entity.name} }}o--o{{ {target} : "{attr}"'
        if attr in entity.nullable_relationships:  # optional "one" (#223)
            return f'{entity.name} }}o--o| {target} : "{attr}"'
        return f'{entity.name} }}o--|| {target} : "{attr}"'  # "one"

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

        A side that names its inverse (``back_populates=``, #240) is paired with
        exactly that attribute. The rest, which do not, are paired by guess:
        each relationship of the first side (entity name sorting first) folds
        at most one relationship declared back from the other side, preferring
        the inverse cardinality (``many`` for ``one`` and vice versa) and
        attributes named after the class they point at (``Post.user`` /
        ``User.posts``), else the first one left. A self-reference
        has no "other side": there an explicit pair keeps the earlier
        declaration, and the guess only folds an N:1 / 1:N inverse
        (``parent`` / ``children``), so two references of the same cardinality
        (``friends`` / ``blocked``, both M:N) stay two edges.
        """

        def inverse_of(i: int) -> str | None:
            entity, _, _, attr = rels[i]
            return entity.inverse_relationships.get(attr)

        names = sorted({rels[i][0].name for i in indices} | {rels[i][1] for i in indices})
        first = names[0]
        self_ref = len(names) == 1
        side_a = [i for i in indices if rels[i][0].name == first]
        side_b = side_a if self_ref else [i for i in indices if rels[i][0].name != first]
        pairs: Dict[int, int] = {}
        used: set[int] = set()

        def pair(i: int, j: int) -> None:
            keep, fold = (min(i, j), max(i, j)) if self_ref else (i, j)
            pairs[keep] = fold
            used.update((i, j))

        # Explicit: the side names its inverse.
        for i in indices:
            inverse = inverse_of(i)
            if i in used or inverse is None:
                continue
            other_side = side_b if i in side_a else side_a
            j = next(
                (j for j in other_side if j != i and j not in used and rels[j][3] == inverse),
                None,
            )
            if j is not None:
                pair(i, j) if i in side_a else pair(j, i)

        # Guessed: neither side names an inverse. Best candidates first, so the
        # result does not depend on which side is drawn: an exact inverse
        # cardinality whose attributes are named after the class they point at
        # on both sides (`Post.user` / `User.posts`), then on one side, then
        # any exact inverse, then (not for a self-reference) anything left.
        free_a = [i for i in side_a if i not in used and inverse_of(i) is None]
        free_b = [j for j in side_b if j not in used and inverse_of(j) is None]

        def exact(i: int, j: int) -> bool:
            return rels[j][2] == self._INVERSE_KIND[rels[i][2]]

        def named(i: int, j: int) -> int:
            def after(attr: str, cls: str) -> bool:
                return attr in (self._snake_case(cls), self._snake_case(cls) + "s")

            entity_i, target_i, _, attr_i = rels[i]
            return int(after(attr_i, target_i)) + int(after(rels[j][3], entity_i.name))

        tiers = [
            lambda i, j: exact(i, j) and named(i, j) == 2,
            lambda i, j: exact(i, j) and named(i, j) == 1,
            exact,
        ]
        if not self_ref:
            tiers.append(lambda i, j: True)
        for fits in tiers:
            for i in free_a:
                if i in used:
                    continue
                if self_ref and self._INVERSE_KIND[rels[i][2]] == rels[i][2]:
                    continue  # two M:N / 1:1 self-references are two relationships
                j = next(
                    (
                        j
                        for j in free_b
                        if j not in used and j != i and (not self_ref or j > i) and fits(i, j)
                    ),
                    None,
                )
                if j is not None:
                    pair(i, j)
        return pairs

    #: Crow's-foot end at the *left* entity for what the right entity declares
    #: about it: (kind, nullable) -> token.
    _LEFT_END = {
        ("one", False): "||",
        ("one", True): "|o",
        ("many", False): "}o",
        ("one_to_one", False): "||",
        ("many_to_many", False): "}o",
    }
    #: Crow's-foot end at the *right* entity for what the left entity declares.
    _RIGHT_END = {
        ("one", False): "||",
        ("one", True): "o|",
        ("many", False): "o{",
        ("one_to_one", False): "||",
        ("many_to_many", False): "o{",
    }

    def _merged_line(
        self,
        kept: "Tuple[EntityInfo, str, str, str]",
        folded: "Tuple[EntityInfo, str, str, str]",
    ) -> str:
        """One edge for both sides of a relationship; each end from its own side (#239)."""
        entity, target, kind, attr = kept
        other, _, other_kind, other_attr = folded
        left = self._LEFT_END[(other_kind, other_attr in other.nullable_relationships)]
        right = self._RIGHT_END[(kind, attr in entity.nullable_relationships)]
        return f'{entity.name} {left}--{right} {target} : "{attr}"'

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

    def generate(self) -> str:
        """Render the diagram.

        Returns:
            PlantUML source, from ``@startuml`` to ``@enduml``.
        """
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
        if entity.is_link_table:
            lines.append(
                f'entity "{entity.table_name}" as {entity.name} << (L, #AAFFAA) link >> {{'
            )
        else:
            lines.append(f'entity "{entity.table_name}" as {entity.name} {{')

        if entity.fields:
            for field in entity.fields:
                lines.append(f"  {self._format_field(field)}")
        else:
            lines.append("  ' (no fields)")

        lines.append("}")
        return lines

    def _generate_enum(self, enum_info: EnumInfo) -> List[str]:
        """Generate PlantUML enum definition."""
        lines = [f"enum {enum_info.name} << (E,#FFCC00) >> {{"]
        for value in enum_info.values:
            lines.append(f"  {value}")
        lines.append("}")
        return lines

    def _format_field(self, field: FieldInfo) -> str:
        """Format a field for PlantUML."""
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
            default = f" = {default_val}"

        unique = " UK" if field.is_unique and not field.is_primary_key else ""

        # Omit the type suffix entirely when the type is unknown (e.g. an
        # untyped Core Column on a synthesized link table) to avoid a dangling ":".
        if not type_str:
            return f"{prefix}({field.name}){unique}"

        return f"{prefix}({field.name}) : {type_str}{nullable}{default}{unique}"


class MermaidGenerator(_ERGenerator):
    """Generates a Mermaid ``erDiagram`` from entities.

    Public API: the constructor and :meth:`generate`.

    Args:
        entities: Entity name to EntityInfo, as returned by the parsers.
        enums: Optional enum name to EnumInfo.
        title: Accepted for a uniform API; Mermaid ``erDiagram`` has no title.
        include_relationships: Draw relationship lines.
    """

    def generate(self) -> str:
        """Render the diagram.

        Returns:
            Mermaid ``erDiagram`` source.
        """
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
        lines = [f"    {entity.name} {{"]
        for field in entity.fields:
            lines.append(f"        {self._format_attr(field)}")
        lines.append("    }")
        return lines

    def _generate_enum(self, enum_info: EnumInfo) -> List[str]:
        """Render an enum as a Mermaid entity block listing its values."""
        lines = [f"    {enum_info.name} {{"]
        for value in enum_info.values:
            lines.append(f"        enum {value}")
        lines.append("    }")
        return lines

    def _format_attr(self, field: FieldInfo) -> str:
        """Format a Mermaid attribute line: ``<type> <name> [keys] ["comment"]``."""
        type_token = self._mermaid_type(field.type_str)

        keys = []
        if field.is_primary_key:
            keys.append("PK")
        if field.is_foreign_key:
            keys.append("FK")
        if field.is_unique and not field.is_primary_key:
            keys.append("UK")
        key_str = ",".join(keys)

        comment_parts = []
        if field.is_nullable:
            comment_parts.append("nullable")
        if field.default_value is not None:
            default_val = field.default_value
            if "." in default_val:
                default_val = default_val.split(".")[-1]
            comment_parts.append(f"default {default_val}")

        parts = [type_token, field.name]
        if key_str:
            parts.append(key_str)
        line = " ".join(parts)
        if comment_parts:
            line += f' "{", ".join(comment_parts)}"'
        return line

    @staticmethod
    def _mermaid_type(type_str: str) -> str:
        """Reduce a type to a single Mermaid-safe token.

        Mermaid attribute types must be a single token, so spaces, pipes and
        brackets (e.g. ``list[str]``) are collapsed to underscores.
        """
        cleaned = type_str.split(".")[-1]
        token = re.sub(r"[^0-9A-Za-z_]+", "_", cleaned).strip("_")
        return token or "unknown"


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
    ``docs/usage/output-formats.md``.

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
    internet access to render. Open it in a browser to view the diagram.

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
        f"{diagram}\n"
        "  </pre>\n"
        "  <script>mermaid.initialize({ startOnLoad: true });</script>\n"
        "</body>\n"
        "</html>\n"
    )
