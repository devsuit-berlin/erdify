"""PlantUML ERD diagram generator."""

from typing import Dict, List, Tuple

from .config import EntityInfo, EnumInfo, FieldInfo


class PlantUMLGenerator:
    """Generates PlantUML ERD diagram from entities."""

    def __init__(
        self,
        entities: Dict[str, EntityInfo],
        enums: Dict[str, EnumInfo] | None = None,
        title: str = "Database ERD",
    ):
        self.entities = entities
        self.enums = enums or {}
        self.title = title

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

        # Generate enums (only those used by entities)
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

        # Generate entities
        for entity in self.entities.values():
            lines.extend(self._generate_entity(entity))
            lines.append("")

        lines.append("' Relationships")
        lines.append("")

        # Build map of link tables for many-to-many relationships
        link_table_map = self._build_link_table_map()

        # Generate relationships
        seen_relationships: set[str] = set()

        # First, generate direct foreign key relationships (not through link tables)
        for entity in self.entities.values():
            if not entity.is_link_table:
                for relationship in self._generate_direct_relationships(entity, link_table_map):
                    if relationship not in seen_relationships:
                        lines.append(relationship)
                        seen_relationships.add(relationship)

        # Then, generate many-to-many relationships through link tables
        for link_entity in self.entities.values():
            if link_entity.is_link_table:
                for relationship in self._generate_link_table_relationships(link_entity):
                    if relationship not in seen_relationships:
                        lines.append(relationship)
                        seen_relationships.add(relationship)

        # Finally, draw declared relationships (Relationship()/relationship() and
        # Pydantic/dataclass nested refs) for entity pairs not already connected by a
        # foreign-key line. This gives keyless models their lines while avoiding
        # duplicate lines for SQLModel/SQLAlchemy, whose relationships are already
        # rendered from foreign keys above.
        connected_pairs = self._connected_pairs()
        # Entity pairs already joined through a link table (many-to-many) must not
        # also receive a direct declared edge - that path is drawn above.
        for table_a, table_b in link_table_map:
            entity_a = self._entity_by_table(table_a)
            entity_b = self._entity_by_table(table_b)
            if entity_a and entity_b:
                connected_pairs.add(frozenset((entity_a.name, entity_b.name)))
        for entity in self.entities.values():
            for relationship, pair in self._generate_relationship_list_lines(entity):
                if pair in connected_pairs or relationship in seen_relationships:
                    continue
                lines.append(relationship)
                seen_relationships.add(relationship)
                connected_pairs.add(pair)

        lines.append("")
        lines.append("@enduml")

        return "\n".join(lines)

    def _generate_entity(self, entity: EntityInfo) -> List[str]:
        """Generate PlantUML entity definition."""
        lines = []

        # Entity header
        if entity.is_link_table:
            lines.append(
                f'entity "{entity.table_name}" as {entity.name} << (L, #AAFFAA) link >> {{'
            )
        else:
            lines.append(f'entity "{entity.table_name}" as {entity.name} {{')

        # Fields
        if entity.fields:
            for field in entity.fields:
                field_line = self._format_field(field)
                lines.append(f"  {field_line}")
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

    def _get_used_enums(self) -> "set[str]":
        """Get set of enum names used by entity fields."""
        used_enums: set[str] = set()
        for entity in self.entities.values():
            for field in entity.fields:
                # Check if field type matches a known enum
                type_name = field.type_str.split(".")[-1]
                if type_name in self.enums:
                    used_enums.add(type_name)
        return used_enums

    def _format_field(self, field: FieldInfo) -> str:
        """Format a field for PlantUML."""
        # Determine prefix
        if field.is_primary_key:
            prefix = "primary_key"
        elif field.is_foreign_key:
            prefix = "foreign_key"
        else:
            prefix = "column"

        # Clean up type
        type_str = field.type_str.split(".")[-1]  # Get just the class name

        # Add nullable marker
        nullable = "?" if field.is_nullable else ""

        # Add default value
        default = ""
        if field.default_value is not None:
            # Shorten enum defaults (OrderStatus.PENDING -> PENDING)
            default_val = field.default_value
            if "." in default_val:
                default_val = default_val.split(".")[-1]
            default = f" = {default_val}"

        # Omit the type suffix entirely when the type is unknown (e.g. an
        # untyped Core Column on a synthesized link table) to avoid a dangling ":".
        if not type_str:
            return f"{prefix}({field.name})"

        return f"{prefix}({field.name}) : {type_str}{nullable}{default}"

    def _build_link_table_map(self) -> Dict[Tuple[str, str], str]:
        """Build a map of (entity1, entity2) -> link_table_name for many-to-many."""
        link_map: Dict[Tuple[str, str], str] = {}

        for entity in self.entities.values():
            if entity.is_link_table and len(entity.fields) == 2:
                # Link tables typically have exactly 2 foreign key fields
                fk_fields = [f for f in entity.fields if f.is_foreign_key]
                if len(fk_fields) == 2:
                    # Extract table names from foreign keys
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
                        # Map both directions
                        link_map[(table1, table2)] = entity.name
                        link_map[(table2, table1)] = entity.name

        return link_map

    def _generate_direct_relationships(
        self, entity: EntityInfo, link_table_map: Dict[Tuple[str, str], str]
    ) -> List[str]:
        """Generate direct relationships (foreign keys without link tables)."""
        lines: List[str] = []

        # Generate relationships from foreign keys in this entity
        for field in entity.fields:
            if field.is_foreign_key and field.foreign_table:
                target_table = field.foreign_table.split(".")[0]

                # Find target entity by table name
                target_entity = None
                for e in self.entities.values():
                    if e.table_name == target_table:
                        target_entity = e
                        break

                if target_entity:
                    # This is a direct foreign key relationship
                    # PlantUML syntax: }o--|| means "zero or more to exactly one"
                    rel_line = f'{entity.name} }}o--|| {target_entity.name} : "{field.name}"'
                    lines.append(rel_line)

        return lines

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
            else:
                line = f'{entity.name} }}o--|| {target.name} : "{attr}"'
            results.append((line, frozenset((entity.name, target.name))))
        return results

    def _generate_link_table_relationships(self, link_entity: EntityInfo) -> List[str]:
        """Generate relationships through a link table (many-to-many)."""
        lines: List[str] = []

        # Get the two foreign keys from the link table
        fk_fields = [f for f in link_entity.fields if f.is_foreign_key]

        if len(fk_fields) != 2:
            return lines

        # Find the two entities being linked
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

            # Draw: Entity1 --o{ LinkTable }o-- Entity2
            line1 = f'{entity1.name} ||--o{{ {link_entity.name} : "{fk1_name}"'
            line2 = f'{link_entity.name} }}o--|| {entity2.name} : "{fk2_name}"'
            lines.append(line1)
            lines.append(line2)

        return lines


def generate_plantuml(
    entities: Dict[str, EntityInfo],
    enums: Dict[str, EnumInfo] | None = None,
    title: str = "Database ERD",
    include_enums: bool = True,
    include_relationships: bool = True,
) -> str:
    """
    Generate PlantUML ERD diagram from parsed entities.

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
