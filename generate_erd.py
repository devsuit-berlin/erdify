#!/usr/bin/env python3
"""
Script to generate PlantUML ERD diagram from SQLModel database models.

This script scans the database layer models and generates a comprehensive
Entity Relationship Diagram (ERD) in PlantUML format using AST parsing.

Usage:
    python scripts/generate_erd.py [output_file]

If output_file is not provided, defaults to 'docs/database/database_erd.puml'
"""

import ast
import sys
from pathlib import Path
from typing import Dict, List, Tuple
from dataclasses import dataclass, field as dc_field


@dataclass
class FieldInfo:
    """Represents a database field/column."""

    name: str
    type_str: str
    is_primary_key: bool = False
    is_foreign_key: bool = False
    is_nullable: bool = False
    foreign_table: str | None = None
    index: bool = False
    default_value: str | None = None


@dataclass
class EnumInfo:
    """Represents an enum type."""

    name: str
    values: List[str] = dc_field(default_factory=list)


@dataclass
class EntityInfo:
    """Represents a database table/entity."""

    name: str
    table_name: str
    fields: List[FieldInfo] = dc_field(default_factory=list)
    relationships: List[Tuple[str, str, str]] = dc_field(
        default_factory=list
    )  # (target, type, attribute_name)
    is_link_table: bool = False
    base_classes: List[str] = dc_field(default_factory=list)


class ASTDatabaseParser:
    """Parses database models using AST to extract schema information."""

    def __init__(self, database_path: Path):
        self.database_path = database_path
        self.entities: Dict[str, EntityInfo] = {}
        self.enums: Dict[str, EnumInfo] = {}
        self.all_classes: Dict[str, ast.ClassDef] = {}  # Store all class definitions
        self.file_trees: Dict[Path, ast.Module] = {}

    def parse_all_models(self) -> Tuple[Dict[str, EntityInfo], Dict[str, EnumInfo]]:
        """Parse all model files in the database directory."""
        model_files = list(self.database_path.rglob("models.py"))

        # First pass: parse all files and collect class definitions
        for model_file in model_files:
            try:
                with open(model_file, "r") as f:
                    content = f.read()
                tree = ast.parse(content)
                self.file_trees[model_file] = tree

                # Collect all class definitions
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef):
                        self.all_classes[node.name] = node
            except Exception as e:
                print(f"Error parsing {model_file}: {e}", file=sys.stderr)

        # Second pass: process enum and table classes
        for class_node in self.all_classes.values():
            if self._is_enum_class(class_node):
                self._parse_enum_class(class_node)
            elif self._is_table_class(class_node):
                self._parse_table_class(class_node)

        return self.entities, self.enums

    def _is_enum_class(self, class_node: ast.ClassDef) -> bool:
        """Check if a class is an Enum."""
        for base in class_node.bases:
            if isinstance(base, ast.Attribute):
                if base.attr == "Enum":
                    return True
            elif isinstance(base, ast.Name):
                if base.id == "Enum":
                    return True
        return False

    def _parse_enum_class(self, class_node: ast.ClassDef):
        """Parse an enum class and extract its values."""
        values = []
        for node in class_node.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and not target.id.startswith("_"):
                        values.append(target.id)

        if values:
            self.enums[class_node.name] = EnumInfo(name=class_node.name, values=values)

    def _is_table_class(self, class_node: ast.ClassDef) -> bool:
        """Check if a class is a table model."""
        for keyword in class_node.keywords:
            if keyword.arg == "table" and isinstance(keyword.value, ast.Constant):
                return keyword.value.value
        return False

    def _parse_table_class(self, class_node: ast.ClassDef):
        """Parse a table class and all its inherited fields."""
        # Get table name
        table_name = None
        for node in class_node.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.target.id == "__tablename__" and isinstance(node.value, ast.Constant):
                    table_name = node.value.value

        if not table_name:
            table_name = self._to_snake_case(class_node.name)

        # Check if link table
        is_link_table = "Link" in class_node.name

        # Get base classes
        base_classes = []
        for base in class_node.bases:
            if isinstance(base, ast.Name):
                base_classes.append(base.id)

        entity = EntityInfo(
            name=class_node.name,
            table_name=table_name,
            is_link_table=is_link_table,
            base_classes=base_classes,
        )

        # Collect fields from this class and all base classes (recursively)
        fields_dict: Dict[str, FieldInfo] = {}
        relationships_dict: Dict[str, Tuple[str, str, str]] = {}

        # Recursively collect fields from all ancestors
        base_fields, base_rels = self._collect_fields_recursive(class_node, set())
        fields_dict.update(base_fields)
        relationships_dict.update(base_rels)

        entity.fields = list(fields_dict.values())
        entity.relationships = list(relationships_dict.values())

        self.entities[class_node.name] = entity

    def _collect_fields_recursive(
        self, class_node: ast.ClassDef, visited: set
    ) -> Tuple[Dict[str, FieldInfo], Dict[str, Tuple[str, str, str]]]:
        """Recursively collect fields from a class and all its ancestors."""
        fields_dict: Dict[str, FieldInfo] = {}
        relationships_dict: Dict[str, Tuple[str, str, str]] = {}

        # Avoid infinite recursion
        if class_node.name in visited:
            return fields_dict, relationships_dict
        visited.add(class_node.name)

        # First, process all base classes recursively
        for base in class_node.bases:
            if isinstance(base, ast.Name):
                base_name = base.id
                if base_name in self.all_classes:
                    base_fields, base_rels = self._collect_fields_recursive(
                        self.all_classes[base_name], visited
                    )
                    fields_dict.update(base_fields)
                    relationships_dict.update(base_rels)

        # Then add/override with current class fields
        class_fields, class_rels = self._extract_class_fields(class_node)
        fields_dict.update(class_fields)
        relationships_dict.update(class_rels)

        return fields_dict, relationships_dict

    def _extract_class_fields(
        self, class_node: ast.ClassDef
    ) -> Tuple[Dict[str, FieldInfo], Dict[str, Tuple[str, str, str]]]:
        """Extract fields and relationships from a class definition."""
        fields: Dict[str, FieldInfo] = {}
        relationships: Dict[str, Tuple[str, str, str]] = {}

        for node in class_node.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                field_name = node.target.id

                # Skip special attributes
                if field_name.startswith("_"):
                    continue

                # Check if relationship
                is_relationship = False
                if node.value and isinstance(node.value, ast.Call):
                    if (
                        isinstance(node.value.func, ast.Name)
                        and node.value.func.id == "Relationship"
                    ):
                        is_relationship = True

                if is_relationship:
                    rel = self._parse_relationship(node)
                    if rel:
                        relationships[field_name] = rel
                else:
                    field = self._parse_field(node)
                    if field:
                        fields[field_name] = field

        return fields, relationships

    def _parse_field(self, node: ast.AnnAssign) -> FieldInfo | None:
        """Parse a field from an annotated assignment."""
        if not isinstance(node.target, ast.Name):
            return None

        field_name = node.target.id
        type_str = ast.unparse(node.annotation)

        # Check if nullable
        is_nullable = "None" in type_str or "Optional" in type_str

        # Parse Field() parameters
        is_primary_key = False
        is_foreign_key = False
        foreign_table = None
        index = False

        if node.value and isinstance(node.value, ast.Call):
            if isinstance(node.value.func, ast.Name) and node.value.func.id == "Field":
                for keyword in node.value.keywords:
                    if keyword.arg == "primary_key" and isinstance(keyword.value, ast.Constant):
                        is_primary_key = keyword.value.value
                    elif keyword.arg == "foreign_key" and isinstance(keyword.value, ast.Constant):
                        is_foreign_key = True
                        foreign_table = keyword.value.value
                    elif keyword.arg == "index" and isinstance(keyword.value, ast.Constant):
                        index = keyword.value.value

        # Extract default value
        default_value = self._extract_default_value(node)

        # Clean up type string
        type_str = type_str.replace(" | None", "").replace("Optional[", "").replace("]", "")

        return FieldInfo(
            name=field_name,
            type_str=type_str,
            is_primary_key=is_primary_key,
            is_foreign_key=is_foreign_key,
            is_nullable=is_nullable,
            foreign_table=foreign_table,
            index=index,
            default_value=default_value,
        )

    def _extract_default_value(self, node: ast.AnnAssign) -> str | None:
        """Extract default value from field definition."""
        if not node.value:
            return None

        # Direct constant value (e.g., field: str = "value")
        if isinstance(node.value, ast.Constant):
            return repr(node.value.value)

        # Field() with default parameter
        if isinstance(node.value, ast.Call):
            if isinstance(node.value.func, ast.Name) and node.value.func.id == "Field":
                # Check positional args first (Field(default_value, ...))
                if node.value.args:
                    first_arg = node.value.args[0]
                    if isinstance(first_arg, ast.Constant):
                        return repr(first_arg.value)
                    elif isinstance(first_arg, ast.Attribute):
                        # Enum value like OrderStatus.PENDING
                        return (
                            f"{first_arg.value.id}.{first_arg.attr}"
                            if isinstance(first_arg.value, ast.Name)
                            else None
                        )

                # Check keyword args (Field(default=value))
                for keyword in node.value.keywords:
                    if keyword.arg == "default":
                        if isinstance(keyword.value, ast.Constant):
                            return repr(keyword.value.value)
                        elif isinstance(keyword.value, ast.Attribute):
                            # Enum value like OrderStatus.PENDING
                            if isinstance(keyword.value.value, ast.Name):
                                return f"{keyword.value.value.id}.{keyword.value.attr}"

        return None

    def _parse_relationship(self, node: ast.AnnAssign) -> Tuple[str, str, str] | None:
        """Parse a relationship from an annotated assignment."""
        if not isinstance(node.target, ast.Name):
            return None

        field_name = node.target.id
        type_str = ast.unparse(node.annotation)

        # Determine cardinality
        rel_type = "one"
        if "list[" in type_str or "List[" in type_str:
            rel_type = "many"

        # Extract target class
        target = type_str.replace("list[", "").replace("List[", "").replace("]", "")
        target = target.replace('"', "").replace("'", "").strip()

        return (target, rel_type, field_name)

    def _to_snake_case(self, name: str) -> str:
        """Convert CamelCase to snake_case."""
        import re

        s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
        return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


class PlantUMLGenerator:
    """Generates PlantUML ERD diagram from entities."""

    def __init__(self, entities: Dict[str, EntityInfo], enums: Dict[str, EnumInfo] = None):
        self.entities = entities
        self.enums = enums or {}

    def generate(self) -> str:
        """Generate PlantUML diagram."""
        lines = [
            "@startuml Eattaxi Database ERD",
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
        seen_relationships = set()

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

    def _get_used_enums(self) -> set:
        """Get set of enum names used by entity fields."""
        used_enums = set()
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

        return f"{prefix}({field.name}) : {type_str}{nullable}{default}"

    def _build_link_table_map(self) -> Dict[Tuple[str, str], str]:
        """Build a map of (entity1, entity2) -> link_table_name for many-to-many relationships."""
        link_map = {}

        for entity in self.entities.values():
            if entity.is_link_table and len(entity.fields) == 2:
                # Link tables typically have exactly 2 foreign key fields
                fk_fields = [f for f in entity.fields if f.is_foreign_key]
                if len(fk_fields) == 2:
                    # Extract table names from foreign keys (e.g., "restaurant.id" -> "restaurant")
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
        """Generate direct relationships (foreign keys and one-to-one/many without link tables)."""
        lines = []

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

        # Generate one-to-one/many relationships that aren't through link tables
        for target, rel_type, attr_name in entity.relationships:
            # Find target entity
            target_entity = None
            for e in self.entities.values():
                if e.name == target:
                    target_entity = e
                    break

            if not target_entity:
                continue

            # Skip if this relationship uses a link table
            if (entity.table_name, target_entity.table_name) in link_table_map:
                continue

            # This is a direct relationship (not through link table)
            # Don't generate it if it's the inverse of a foreign key we already handled
            # Only generate for navigation properties, not for the FK side
            has_fk_to_target = any(
                f.is_foreign_key
                and f.foreign_table
                and f.foreign_table.split(".")[0] == target_entity.table_name
                for f in entity.fields
            )

            if not has_fk_to_target:
                # This is a back-reference, skip it (it's already drawn from the FK side)
                pass

        return lines

    def _generate_link_table_relationships(self, link_entity: EntityInfo) -> List[str]:
        """Generate relationships through a link table (many-to-many)."""
        lines = []

        # Get the two foreign keys from the link table
        fk_fields = [f for f in link_entity.fields if f.is_foreign_key]

        if len(fk_fields) != 2:
            return lines

        # Find the two entities being linked
        entities_to_link = []
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
            # PlantUML syntax for cardinality:
            # ||--o{ means "exactly one to zero or more"
            # }o--|| means "zero or more to exactly one"
            # In f-strings, {{ becomes { and }} becomes }
            line1 = f'{entity1.name} ||--o{{ {link_entity.name} : "{fk1_name}"'
            line2 = f'{link_entity.name} }}o--|| {entity2.name} : "{fk2_name}"'
            lines.append(line1)
            lines.append(line2)

        return lines


def main():
    """Main entry point."""
    # Determine paths
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    database_path = project_root / "services" / "backend" / "src" / "database"

    # Output file
    if len(sys.argv) > 1:
        output_file = Path(sys.argv[1])
    else:
        output_file = project_root / "docs" / "database" / "database_erd.puml"

    # Check if database path exists
    if not database_path.exists():
        print(f"Error: Database path not found: {database_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Parsing database models in: {database_path}")

    # Parse models
    parser = ASTDatabaseParser(database_path)
    entities, enums = parser.parse_all_models()

    print(f"Found {len(entities)} entities and {len(enums)} enums")

    # Generate PlantUML
    generator = PlantUMLGenerator(entities, enums)
    plantuml_content = generator.generate()

    # Ensure output directory exists
    output_file.parent.mkdir(parents=True, exist_ok=True)

    # Write output
    with open(output_file, "w") as f:
        f.write(plantuml_content)

    print(f"ERD diagram generated: {output_file}")
    print("\nTo view the diagram:")
    print("  1. Install PlantUML: brew install plantuml")
    print(f"  2. Generate PNG: plantuml {output_file}")
    print("  3. Or view online: http://www.plantuml.com/plantuml/uml/")


if __name__ == "__main__":
    main()
