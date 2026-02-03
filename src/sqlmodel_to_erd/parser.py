"""AST-based parser for SQLModel database models."""

import ast
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

from .config import EntityInfo, EnumInfo, FieldInfo


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

    def _parse_enum_class(self, class_node: ast.ClassDef) -> None:
        """Parse an enum class and extract its values."""
        values: List[str] = []
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

    def _parse_table_class(self, class_node: ast.ClassDef) -> None:
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
        base_classes: List[str] = []
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
        s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
        return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def parse_models_directory(
    path: Path, exclude_patterns: List[str] | None = None
) -> Tuple[Dict[str, EntityInfo], Dict[str, EnumInfo]]:
    """
    Parse all SQLModel models in a directory.

    Args:
        path: Path to directory containing model files
        exclude_patterns: List of patterns to exclude (not yet implemented)

    Returns:
        Tuple of (entities dict, enums dict)
    """
    parser = ASTDatabaseParser(path)
    return parser.parse_all_models()
