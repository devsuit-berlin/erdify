"""ERD diagram generators (PlantUML and Mermaid)."""

import re
from typing import Dict, List, Tuple

from .config import EntityInfo, EnumInfo, FieldInfo


class _ERGenerator:
    """Shared ERD model: entity/enum bookkeeping and relationship resolution.

    Relationship lines use crow's-foot tokens (``}o--||``, ``||--o{``, ``||--||``,
    ``}o--o{``) that are valid in *both* PlantUML and Mermaid, so subclasses share
    the relationship logic and only differ in entity/enum block formatting.
    """

    def __init__(
        self,
        entities: Dict[str, EntityInfo],
        enums: Dict[str, EnumInfo] | None = None,
        title: str = "Database ERD",
    ):
        self.entities = entities
        self.enums = enums or {}
        self.title = title

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
        for field in entity.fields:
            if field.is_foreign_key and field.foreign_table:
                target_table = field.foreign_table.split(".")[0]
                target_entity = None
                for e in self.entities.values():
                    if e.table_name == target_table:
                        target_entity = e
                        break
                if target_entity:
                    # }o--|| means "zero or more to exactly one".
                    lines.append(f'{entity.name} }}o--|| {target_entity.name} : "{field.name}"')
        return lines

    def _generate_link_table_relationships(self, link_entity: EntityInfo) -> List[str]:
        """Generate relationships through a link table (many-to-many)."""
        lines: List[str] = []
        fk_fields = [f for f in link_entity.fields if f.is_foreign_key]
        if len(fk_fields) != 2:
            return lines

        entities_to_link: List[Tuple[EntityInfo, str]] = []
        for fk_field in fk_fields:
            if fk_field.foreign_table:
                target_table = fk_field.foreign_table.split(".")[0]
                for e in self.entities.values():
                    if e.table_name == target_table:
                        entities_to_link.append((e, fk_field.name))
                        break

        if len(entities_to_link) == 2:
            entity1, fk1_name = entities_to_link[0]
            entity2, fk2_name = entities_to_link[1]
            lines.append(f'{entity1.name} ||--o{{ {link_entity.name} : "{fk1_name}"')
            lines.append(f'{link_entity.name} }}o--|| {entity2.name} : "{fk2_name}"')

        return lines

    def _generate_relationship_list_lines(
        self, entity: EntityInfo
    ) -> "List[Tuple[str, frozenset[str]]]":
        """Generate lines from an entity's declared relationships.

        Returns (line, pair) tuples where pair is the frozenset of the two
        connected entity names, so callers can skip already-connected pairs.
        """
        results: List[Tuple[str, frozenset[str]]] = []
        for target_name, rel_type, attr in entity.relationships:
            target = self.entities.get(target_name)
            if not target:
                continue
            if rel_type == "many":
                line = f'{entity.name} ||--o{{ {target.name} : "{attr}"'
            elif rel_type == "one_to_one":
                line = f'{entity.name} ||--|| {target.name} : "{attr}"'
            elif rel_type == "many_to_many":
                line = f'{entity.name} }}o--o{{ {target.name} : "{attr}"'
            else:  # "one"
                line = f'{entity.name} }}o--|| {target.name} : "{attr}"'
            results.append((line, frozenset((entity.name, target.name))))
        return results

    def _relationship_lines(self) -> List[str]:
        """Resolve every relationship line, de-duplicated and ordered.

        Order: direct foreign-key edges, then many-to-many through link tables,
        then declared relationships for pairs not already connected (so keyless
        models get edges without duplicating SQLModel/SQLAlchemy foreign keys).
        """
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

        connected_pairs = self._connected_pairs()
        for table_a, table_b in link_table_map:
            entity_a = self._entity_by_table(table_a)
            entity_b = self._entity_by_table(table_b)
            if entity_a and entity_b:
                connected_pairs.add(frozenset((entity_a.name, entity_b.name)))

        for entity in self.entities.values():
            for rel, pair in self._generate_relationship_list_lines(entity):
                if pair in connected_pairs or rel in seen:
                    continue
                lines.append(rel)
                seen.add(rel)
                connected_pairs.add(pair)

        return lines


class PlantUMLGenerator(_ERGenerator):
    """Generates a PlantUML ERD diagram from entities."""

    def generate(self) -> str:
        """Generate PlantUML diagram."""
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

        # Omit the type suffix entirely when the type is unknown (e.g. an
        # untyped Core Column on a synthesized link table) to avoid a dangling ":".
        if not type_str:
            return f"{prefix}({field.name})"

        return f"{prefix}({field.name}) : {type_str}{nullable}{default}"


class MermaidGenerator(_ERGenerator):
    """Generates a Mermaid ``erDiagram`` from entities."""

    def generate(self) -> str:
        """Generate a Mermaid erDiagram."""
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
        key_str = ", ".join(keys)

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
    )
    return generator.generate()


def generate_mermaid(
    entities: Dict[str, EntityInfo],
    enums: Dict[str, EnumInfo] | None = None,
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
    )
    return generator.generate()
