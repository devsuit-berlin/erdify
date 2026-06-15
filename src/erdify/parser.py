"""AST-based parser for SQLModel, SQLAlchemy, Pydantic and dataclass models."""

import ast
import re
import sys
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Dict, List, Tuple

from .config import EntityInfo, EnumInfo, FieldInfo


#: Model frameworks erdify can recognize, in classification order.
MODEL_SOURCES = ("sqlmodel", "sqlalchemy", "dataclass", "pydantic")


class ASTDatabaseParser:
    """Parses database models using AST to extract schema information."""

    def __init__(
        self,
        database_path: Path,
        exclude_patterns: List[str] | None = None,
        infer_keys: bool = False,
        sources: List[str] | None = None,
    ):
        self.database_path = database_path
        self.exclude_patterns = exclude_patterns or []
        self.infer_keys = infer_keys
        #: Restrict which model kinds become entities; None = all of MODEL_SOURCES.
        self.sources = set(sources) if sources else None
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

        # Second pass: process enum and model classes
        for class_node in self.all_classes.values():
            if self._is_enum_class(class_node):
                self._parse_enum_class(class_node)
                continue
            source = self._classify_source(class_node)
            if source is not None and (self.sources is None or source in self.sources):
                self._parse_table_class(class_node, source)

        # Third pass: apply exclude patterns
        self._apply_exclude_patterns()

        return self.entities, self.enums

    def _apply_exclude_patterns(self) -> None:
        """Remove excluded entities and strip relationships pointing at them.

        A pattern matches an entity if its case-sensitive glob matches either
        the class name or the table name. Relationships in surviving entities
        that target an excluded entity are dropped so no dangling lines remain.
        """
        if not self.exclude_patterns:
            return

        def is_excluded(entity: EntityInfo) -> bool:
            return any(
                fnmatchcase(entity.name, pattern) or fnmatchcase(entity.table_name, pattern)
                for pattern in self.exclude_patterns
            )

        excluded_names = {name for name, e in self.entities.items() if is_excluded(e)}

        self.entities = {name: e for name, e in self.entities.items() if name not in excluded_names}

        for entity in self.entities.values():
            entity.relationships = [
                rel for rel in entity.relationships if rel[0] not in excluded_names
            ]

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

    def _classify_source(self, class_node: ast.ClassDef) -> str | None:
        """Classify which model framework a class belongs to.

        Returns one of "sqlmodel", "sqlalchemy", "pydantic", "dataclass", or
        None if the class is not a drawable entity.
        """
        # SQLModel: declared with table=True
        for keyword in class_node.keywords:
            if keyword.arg == "table" and isinstance(keyword.value, ast.Constant):
                if keyword.value.value:
                    return "sqlmodel"

        # SQLAlchemy 2.0: a concrete mapped class has __tablename__ and Mapped[...] columns.
        # Mixins/abstract bases (Mapped fields but no __tablename__) are excluded here so
        # they are not emitted as entities, but their fields are still inherited.
        if self._has_tablename(class_node) and self._has_mapped_field(class_node):
            return "sqlalchemy"

        # Plain @dataclass
        if self._is_dataclass(class_node):
            return "dataclass"

        # Pydantic: inherits from BaseModel (directly or transitively)
        if self._inherits_basemodel(class_node):
            return "pydantic"

        return None

    @staticmethod
    def _is_dataclass(class_node: ast.ClassDef) -> bool:
        """Check if a class is decorated with @dataclass (bare or called)."""
        for dec in class_node.decorator_list:
            if isinstance(dec, ast.Name) and dec.id == "dataclass":
                return True
            if isinstance(dec, ast.Attribute) and dec.attr == "dataclass":
                return True
            if isinstance(dec, ast.Call):
                func = dec.func
                if isinstance(func, ast.Name) and func.id == "dataclass":
                    return True
                if isinstance(func, ast.Attribute) and func.attr == "dataclass":
                    return True
        return False

    def _inherits_basemodel(
        self, class_node: ast.ClassDef, visited: set[str] | None = None
    ) -> bool:
        """Check if a class inherits from Pydantic's BaseModel, directly or via ancestors."""
        visited = visited if visited is not None else set()
        if class_node.name in visited:
            return False
        visited.add(class_node.name)

        for base in class_node.bases:
            if isinstance(base, ast.Name):
                if base.id == "BaseModel":
                    return True
                ancestor = self.all_classes.get(base.id)
                if ancestor is not None and self._inherits_basemodel(ancestor, visited):
                    return True
            elif isinstance(base, ast.Attribute) and base.attr == "BaseModel":
                return True
        return False

    def _has_tablename(self, class_node: ast.ClassDef) -> bool:
        """Check if a class assigns __tablename__ (annotated or plain)."""
        for node in class_node.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.target.id == "__tablename__":
                    return True
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "__tablename__":
                        return True
        return False

    def _has_mapped_field(self, class_node: ast.ClassDef) -> bool:
        """Check if a class has at least one Mapped[...] annotated field."""
        for node in class_node.body:
            if isinstance(node, ast.AnnAssign) and self._is_mapped_annotation(node.annotation):
                return True
        return False

    @staticmethod
    def _is_mapped_annotation(annotation: ast.expr) -> bool:
        """Check if an annotation is a SQLAlchemy Mapped[...] subscript."""
        return (
            isinstance(annotation, ast.Subscript)
            and isinstance(annotation.value, ast.Name)
            and annotation.value.id == "Mapped"
        )

    @staticmethod
    def _unwrap_mapped(type_str: str) -> str:
        """Strip a SQLAlchemy Mapped[...] wrapper, returning the inner type string."""
        if type_str.startswith("Mapped[") and type_str.endswith("]"):
            return type_str[len("Mapped[") : -1]
        return type_str

    def _parse_table_class(self, class_node: ast.ClassDef, source: str) -> None:
        """Parse a table class and all its inherited fields."""
        # Get table name (annotated: SQLModel, or plain assignment: SQLAlchemy)
        table_name = None
        for node in class_node.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.target.id == "__tablename__" and isinstance(node.value, ast.Constant):
                    table_name = str(node.value.value)
            elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "__tablename__":
                        table_name = str(node.value.value)

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
            source=source,
        )

        # Collect fields from this class and all base classes (recursively)
        fields_dict: Dict[str, FieldInfo] = {}
        relationships_dict: Dict[str, Tuple[str, str, str]] = {}

        # Recursively collect fields from all ancestors
        base_fields, base_rels = self._collect_fields_recursive(class_node, set(), source)
        fields_dict.update(base_fields)
        relationships_dict.update(base_rels)

        entity.fields = list(fields_dict.values())
        entity.relationships = list(relationships_dict.values())

        self.entities[class_node.name] = entity

    def _collect_fields_recursive(
        self, class_node: ast.ClassDef, visited: set[str], model_kind: str
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
                        self.all_classes[base_name], visited, model_kind
                    )
                    fields_dict.update(base_fields)
                    relationships_dict.update(base_rels)

        # Then add/override with current class fields
        class_fields, class_rels = self._extract_class_fields(class_node, model_kind)
        fields_dict.update(class_fields)
        relationships_dict.update(class_rels)

        return fields_dict, relationships_dict

    def _extract_class_fields(
        self, class_node: ast.ClassDef, model_kind: str
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

                # Check for an explicit relationship call (SQLModel/SQLAlchemy)
                is_relationship = False
                if node.value and isinstance(node.value, ast.Call):
                    if isinstance(node.value.func, ast.Name) and node.value.func.id in (
                        "Relationship",  # SQLModel
                        "relationship",  # SQLAlchemy
                    ):
                        is_relationship = True

                if is_relationship:
                    rel = self._parse_relationship(node)
                    if rel:
                        relationships[field_name] = rel
                    continue

                # Keyless sources (Pydantic/dataclass): a field typed as another
                # model is treated as a relationship rather than a column.
                if model_kind in ("pydantic", "dataclass"):
                    rel = self._parse_model_reference(node)
                    if rel:
                        relationships[field_name] = rel
                        continue

                field = self._parse_field(node, model_kind)
                if field:
                    fields[field_name] = field

        return fields, relationships

    def _parse_field(self, node: ast.AnnAssign, model_kind: str) -> FieldInfo | None:
        """Parse a field from an annotated assignment."""
        if not isinstance(node.target, ast.Name):
            return None

        field_name = node.target.id
        type_str = self._unwrap_mapped(ast.unparse(node.annotation))

        # Check if nullable
        is_nullable = "None" in type_str or "Optional" in type_str

        # Parse Field() / mapped_column() parameters
        is_primary_key = False
        is_foreign_key = False
        foreign_table = None
        index = False

        if node.value and isinstance(node.value, ast.Call):
            if isinstance(node.value.func, ast.Name) and node.value.func.id in (
                "Field",  # SQLModel
                "mapped_column",  # SQLAlchemy
            ):
                for keyword in node.value.keywords:
                    if keyword.arg == "primary_key" and isinstance(keyword.value, ast.Constant):
                        is_primary_key = bool(keyword.value.value)
                    elif keyword.arg == "foreign_key" and isinstance(keyword.value, ast.Constant):
                        is_foreign_key = True
                        foreign_table = str(keyword.value.value)
                    elif keyword.arg == "index" and isinstance(keyword.value, ast.Constant):
                        index = bool(keyword.value.value)

                # SQLAlchemy: ForeignKey("table.col") passed to mapped_column()
                fk_target = self._extract_foreign_key_arg(node.value)
                if fk_target is not None:
                    is_foreign_key = True
                    foreign_table = fk_target

        # Optional name-based key inference for keyless sources (Pydantic/dataclass).
        # Never overrides explicitly declared keys above.
        if self.infer_keys and model_kind in ("pydantic", "dataclass"):
            if field_name == "id":
                is_primary_key = True
            elif field_name.endswith("_id"):
                is_foreign_key = True
                foreign_table = f"{field_name[: -len('_id')]}.id"

        # Extract default value
        default_value = self._extract_default_value(node)

        # Clean up type string: drop the optional wrapper without mangling
        # generic args (e.g. list[str] must keep its closing bracket).
        type_str = type_str.replace(" | None", "").strip()
        if type_str.startswith("Optional[") and type_str.endswith("]"):
            type_str = type_str[len("Optional[") : -1]

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

    @staticmethod
    def _extract_foreign_key_arg(call: ast.Call) -> str | None:
        """Extract the target from a ForeignKey("table.col") call argument.

        SQLAlchemy expresses foreign keys as `mapped_column(ForeignKey("user.id"))`,
        where ForeignKey may appear as a positional or keyword argument.
        """
        candidates = list(call.args) + [kw.value for kw in call.keywords]
        for arg in candidates:
            if (
                isinstance(arg, ast.Call)
                and isinstance(arg.func, ast.Name)
                and arg.func.id == "ForeignKey"
                and arg.args
                and isinstance(arg.args[0], ast.Constant)
            ):
                return str(arg.args[0].value)
        return None

    def _extract_default_value(self, node: ast.AnnAssign) -> str | None:
        """Extract default value from field definition."""
        if not node.value:
            return None

        # Direct constant value (e.g., field: str = "value")
        if isinstance(node.value, ast.Constant):
            return repr(node.value.value)

        # Field() / mapped_column() with default parameter
        if isinstance(node.value, ast.Call):
            if isinstance(node.value.func, ast.Name) and node.value.func.id in (
                "Field",
                "mapped_column",
            ):
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
        type_str = self._unwrap_mapped(ast.unparse(node.annotation))

        rel_type = "many" if ("list[" in type_str or "List[" in type_str) else "one"
        target = self._clean_target(type_str)

        return (target, rel_type, field_name)

    def _parse_model_reference(self, node: ast.AnnAssign) -> Tuple[str, str, str] | None:
        """Treat a field typed as another known model as a relationship.

        Used for Pydantic/dataclass models, which express relationships as plain
        typed attributes (e.g. ``user: User`` or ``items: list[Item]``) rather
        than via a Relationship()/relationship() call.
        """
        if not isinstance(node.target, ast.Name):
            return None

        type_str = self._unwrap_mapped(ast.unparse(node.annotation))
        rel_type = "many" if ("list[" in type_str or "List[" in type_str) else "one"
        target = self._clean_target(type_str)

        target_class = self.all_classes.get(target)
        if target_class is not None and self._classify_source(target_class) is not None:
            return (target, rel_type, node.target.id)
        return None

    @staticmethod
    def _clean_target(type_str: str) -> str:
        """Reduce a (possibly wrapped) annotation to a bare target class name."""
        cleaned = type_str
        for token in ("Mapped[", "list[", "List[", "Optional["):
            cleaned = cleaned.replace(token, "")
        cleaned = cleaned.replace("]", "").replace(" | None", "").replace("None", "")
        return cleaned.replace('"', "").replace("'", "").strip()

    def _to_snake_case(self, name: str) -> str:
        """Convert CamelCase to snake_case."""
        s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
        return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def parse_models_directory(
    path: Path,
    exclude_patterns: List[str] | None = None,
    infer_keys: bool = False,
    sources: List[str] | None = None,
) -> Tuple[Dict[str, EntityInfo], Dict[str, EnumInfo]]:
    """
    Parse SQLModel, SQLAlchemy, Pydantic and dataclass models in a directory.

    Args:
        path: Path to directory containing model files
        exclude_patterns: List of case-sensitive glob patterns. An entity is
            excluded if a pattern matches its class name or its table name.
        infer_keys: For keyless sources (Pydantic/dataclass), infer a primary
            key from a field named ``id`` and a foreign key from ``<x>_id``.
        sources: Restrict which model kinds become entities (subset of
            ``MODEL_SOURCES``). ``None`` includes all kinds.

    Returns:
        Tuple of (entities dict, enums dict)
    """
    parser = ASTDatabaseParser(
        path, exclude_patterns=exclude_patterns, infer_keys=infer_keys, sources=sources
    )
    return parser.parse_all_models()
