"""AST-based parser for SQLModel, SQLAlchemy, Django, Pydantic and dataclass models."""

import ast
import os
import re
import sys
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Dict, List, Tuple, TypeGuard

from .config import EntityInfo, EnumInfo, FieldInfo


#: Model frameworks erdify can recognize, in classification order.
MODEL_SOURCES = ("sqlmodel", "sqlalchemy", "django", "dataclass", "pydantic")

#: Directory names skipped during the models.py scan unless --no-default-excludes
#: is set. `site-packages` alone catches all third-party models inside a
#: virtualenv regardless of the venv directory name.
DEFAULT_EXCLUDE_DIRS = frozenset(
    {
        "site-packages",
        ".venv",
        "venv",
        "env",
        "virtualenv",
        "node_modules",
        "__pycache__",
        ".git",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
    }
)

#: Django relationship field constructs (everything else ending in "Field" is a column).
DJANGO_RELATIONSHIP_FIELDS = frozenset({"ForeignKey", "OneToOneField", "ManyToManyField"})

#: Conservative Django field -> Python type map for readable, source-consistent
#: output. Ambiguous/lossy fields (JSONField, FileField, ImageField, custom or
#: third-party fields) are intentionally omitted so they fall back to the Django
#: field name rather than fake a concrete type. Use --django-raw-types to keep the
#: original Django field names instead.
DJANGO_FIELD_TYPE_MAP = {
    "CharField": "str",
    "TextField": "str",
    "SlugField": "str",
    "EmailField": "str",
    "URLField": "str",
    "GenericIPAddressField": "str",
    "FilePathField": "str",
    "IntegerField": "int",
    "BigIntegerField": "int",
    "SmallIntegerField": "int",
    "PositiveIntegerField": "int",
    "PositiveSmallIntegerField": "int",
    "PositiveBigIntegerField": "int",
    "AutoField": "int",
    "BigAutoField": "int",
    "SmallAutoField": "int",
    "FloatField": "float",
    "DecimalField": "Decimal",
    "BooleanField": "bool",
    "DateTimeField": "datetime",
    "DateField": "date",
    "TimeField": "time",
    "DurationField": "timedelta",
    "UUIDField": "UUID",
    "BinaryField": "bytes",
}


def _translate_glob(pattern: str) -> str:
    """Compile a gitignore-style path glob to an anchored regex string.

    ``*`` and ``?`` match within a single path segment (never ``/``); ``**``
    matches across segments (zero or more). Python 3.11 has no
    ``PurePath.full_match`` and ``fnmatch`` lets ``*`` cross ``/``, so we
    translate by hand.
    """
    i, n = 0, len(pattern)
    out = ""
    while i < n:
        c = pattern[i]
        if c == "*":
            if i + 1 < n and pattern[i + 1] == "*":
                j = i + 2
                if j < n and pattern[j] == "/":
                    out += "(?:[^/]+/)*"  # **/ -> any number of leading dirs
                    i = j + 1
                else:
                    out += ".*"  # ** -> anything, including /
                    i = j
            else:
                out += "[^/]*"  # * -> within one segment
                i += 1
        elif c == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(c)
            i += 1
    return "(?s:" + out + r")\Z"


def _match_include(rel_path: str, filename: str, patterns: List[str]) -> bool:
    """Whether a file matches any include pattern.

    Slash patterns match the path relative to the input (``rel_path``) with
    ``**`` support; slashless patterns match the ``filename`` basename at any
    depth (so the default ``models.py`` keeps its recursive behavior).
    """
    for pattern in patterns:
        if "/" in pattern:
            if re.match(_translate_glob(pattern), rel_path):
                return True
        elif fnmatchcase(filename, pattern):
            return True
    return False


class ASTDatabaseParser:
    """Parses database models using AST to extract schema information."""

    def __init__(
        self,
        database_path: Path,
        exclude_patterns: List[str] | None = None,
        infer_keys: bool = False,
        sources: List[str] | None = None,
        django_raw_types: bool = False,
        exclude_paths: List[str] | None = None,
        use_default_excludes: bool = True,
        include_patterns: List[str] | None = None,
        hint_unmatched_model_packages: bool = False,
    ):
        self.database_path = database_path
        self.exclude_patterns = exclude_patterns or []
        self.infer_keys = infer_keys
        #: Show original Django field names (CharField) instead of mapped Python types.
        self.django_raw_types = django_raw_types
        #: Glob patterns (path or segment) for models.py files to skip during the scan.
        self.exclude_paths = exclude_paths or []
        #: Whether to skip DEFAULT_EXCLUDE_DIRS (venv/site-packages/caches) during the scan.
        self.use_default_excludes = use_default_excludes
        #: Glob patterns selecting which files are scanned; default mirrors the
        #: historical models.py-only behavior. Slash patterns match the path
        #: relative to the input (with **); slashless patterns match basenames.
        self.include_patterns = include_patterns or ["models.py"]
        #: When True, warn (once, on stderr) about a models/ package that the
        #: current include patterns skip. The CLI sets this only at the default;
        #: the library stays silent so programmatic callers get no stderr noise.
        self.hint_unmatched_model_packages = hint_unmatched_model_packages
        self._unmatched_model_packages: List[Path] = []
        #: Restrict which model kinds become entities; None = all of MODEL_SOURCES.
        self.sources = set(sources) if sources else None
        self.entities: Dict[str, EntityInfo] = {}
        self.enums: Dict[str, EnumInfo] = {}
        self.all_classes: Dict[str, ast.ClassDef] = {}  # Store all class definitions
        self.file_trees: Dict[Path, ast.Module] = {}

    def parse_all_models(self) -> Tuple[Dict[str, EntityInfo], Dict[str, EnumInfo]]:
        """Parse all model files in the database directory."""
        model_files = self._discover_model_files()

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

        # Synthesize link entities from module-level Core Table(...) association
        # tables referenced by relationship(secondary=...) (#34).
        self._parse_core_association_tables()

        # Third pass: apply exclude patterns
        self._apply_exclude_patterns()

        return self.entities, self.enums

    def _discover_model_files(self) -> List[Path]:
        """Find model files, pruning excluded directories during the walk.

        Default-excluded dirs (venv/site-packages/caches) are removed from the
        traversal *before* descending, so large trees like ``.venv`` are never
        scandir'd. A file is selected when it matches ``self.include_patterns``
        (default ``["models.py"]``); ``exclude_paths`` then filters via
        :meth:`_is_path_excluded`. Results are sorted for deterministic output.
        """
        base = self.database_path
        found: List[Path] = []
        for dirpath, dirnames, filenames in os.walk(base):
            if self.use_default_excludes:
                # In-place prune so os.walk does not descend into excluded dirs.
                dirnames[:] = [d for d in dirnames if d not in DEFAULT_EXCLUDE_DIRS]
            dpath = Path(dirpath)
            if (
                self.hint_unmatched_model_packages
                and dpath.name == "models"
                and any(f.endswith(".py") for f in filenames)
            ):
                self._unmatched_model_packages.append(dpath)
            for filename in filenames:
                if not filename.endswith(".py"):
                    continue
                candidate = dpath / filename
                try:
                    rel = candidate.relative_to(base).as_posix()
                except ValueError:
                    rel = candidate.as_posix()
                if not _match_include(rel, filename, self.include_patterns):
                    continue
                if not self._is_path_excluded(candidate):
                    found.append(candidate)
        if self._unmatched_model_packages:
            example = sorted(self._unmatched_model_packages)[0]
            print(
                f"Hint: found a models/ package ({example}) that was not scanned "
                f"(the default only matches models.py). Use "
                f"--include '**/models/*.py' to include it.",
                file=sys.stderr,
            )
        return sorted(found)

    def _is_path_excluded(self, model_file: Path) -> bool:
        """Decide whether a discovered models.py should be skipped before parsing.

        Skips files under a default non-project directory (venv/site-packages/
        caches, unless disabled) or matching an ``exclude_paths`` glob against the
        path relative to the input or any single path segment.
        """
        try:
            rel = model_file.relative_to(self.database_path).as_posix()
        except ValueError:
            rel = model_file.as_posix()
        segments = rel.split("/")[:-1]  # directory segments only (drop "models.py")

        if self.use_default_excludes and any(seg in DEFAULT_EXCLUDE_DIRS for seg in segments):
            return True

        for pattern in self.exclude_paths:
            if fnmatchcase(rel, pattern) or any(fnmatchcase(seg, pattern) for seg in segments):
                return True

        return False

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

    #: Enum base class names recognized by erdify (stdlib Enum + Django choices).
    _ENUM_BASES = frozenset({"Enum", "TextChoices", "IntegerChoices"})

    def _is_enum_class(self, class_node: ast.ClassDef) -> bool:
        """Check if a class is an Enum or a Django TextChoices/IntegerChoices."""
        for base in class_node.bases:
            if isinstance(base, ast.Attribute) and base.attr in self._ENUM_BASES:
                return True
            if isinstance(base, ast.Name) and base.id in self._ENUM_BASES:
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

        # Django: subclasses django.db.models.Model. An abstract base
        # (class Meta: abstract = True) is inherited but not drawn itself.
        if self._inherits_django_model(class_node):
            if self._meta_flag(class_node, "abstract"):
                return None
            return "django"

        # Plain @dataclass
        if self._is_dataclass(class_node):
            return "dataclass"

        # Pydantic: inherits from BaseModel (directly or transitively)
        if self._inherits_basemodel(class_node):
            return "pydantic"

        return None

    def _inherits_django_model(
        self, class_node: ast.ClassDef, visited: set[str] | None = None
    ) -> bool:
        """Check if a class inherits from Django's models.Model, directly or via ancestors."""
        visited = visited if visited is not None else set()
        if class_node.name in visited:
            return False
        visited.add(class_node.name)

        for base in class_node.bases:
            # models.Model / django.db.models.Model
            if isinstance(base, ast.Attribute) and base.attr == "Model":
                return True
            if isinstance(base, ast.Name):
                if base.id == "Model":
                    return True
                ancestor = self.all_classes.get(base.id)
                if ancestor is not None and self._inherits_django_model(ancestor, visited):
                    return True
        return False

    @staticmethod
    def _get_meta_class(class_node: ast.ClassDef) -> ast.ClassDef | None:
        """Return the nested ``class Meta`` of a Django model, if present."""
        for node in class_node.body:
            if isinstance(node, ast.ClassDef) and node.name == "Meta":
                return node
        return None

    def _meta_flag(self, class_node: ast.ClassDef, attr: str) -> bool:
        """Read a boolean attribute (e.g. ``abstract``) from a model's ``class Meta``."""
        value = self._meta_value(class_node, attr)
        return bool(value) if isinstance(value, bool) else False

    def _meta_value(self, class_node: ast.ClassDef, attr: str) -> object | None:
        """Read a constant attribute (e.g. ``db_table``) from a model's ``class Meta``."""
        meta = self._get_meta_class(class_node)
        if meta is None:
            return None
        for node in meta.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == attr:
                        return node.value.value
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

        # Django: table name comes from `class Meta: db_table = "..."`.
        if not table_name and source == "django":
            db_table = self._meta_value(class_node, "db_table")
            if isinstance(db_table, str):
                table_name = db_table

        if not table_name:
            table_name = self._to_snake_case(class_node.name)

        # Get base classes
        base_classes: List[str] = []
        for base in class_node.bases:
            if isinstance(base, ast.Name):
                base_classes.append(base.id)

        entity = EntityInfo(
            name=class_node.name,
            table_name=table_name,
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

        # Django implicitly adds an `id` primary key (BigAutoField since Django 3.2)
        # when no field declares primary_key=True.
        if source == "django" and not any(f.is_primary_key for f in entity.fields):
            entity.fields.insert(
                0,
                FieldInfo(
                    name="id",
                    type_str=self._django_display_type("BigAutoField"),
                    is_primary_key=True,
                ),
            )

        # Detect join tables structurally: an entity whose columns are exactly
        # two foreign keys, both part of the primary key, is an association
        # table regardless of its class name (#35).
        entity.is_link_table = self._is_structural_link_table(entity.fields)

        self.entities[class_node.name] = entity

    @staticmethod
    def _is_structural_link_table(fields: List[FieldInfo]) -> bool:
        """Return True if fields describe a join table: exactly two columns,
        both foreign keys and both part of the primary key."""
        if len(fields) != 2:
            return False
        return all(f.is_foreign_key and f.is_primary_key for f in fields)

    def _parse_core_association_tables(self) -> None:
        """Synthesize link entities from module-level Core ``Table(...)`` assignments.

        ``relationship(secondary=Table(...))`` points at a SQLAlchemy Core table
        rather than a mapped class. Only class definitions become entities in the
        normal passes, so such association tables - and their M:N - would be lost.
        Parse module-level ``name = Table("t", metadata, Column(...), ...)``
        assignments that are structurally association tables (exactly two FK
        columns, both part of the primary key) and add them as link entities (#34).
        """
        if self.sources is not None and "sqlalchemy" not in self.sources:
            return

        for tree in self.file_trees.values():
            for node in tree.body:
                if not isinstance(node, ast.Assign):
                    continue
                if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                    continue
                if not self._is_call_to(node.value, "Table"):
                    continue

                var_name = node.targets[0].id
                entity = self._build_core_table_entity(var_name, node.value)
                if entity is not None and entity.name not in self.entities:
                    self.entities[entity.name] = entity

    def _build_core_table_entity(self, var_name: str, call: ast.Call) -> EntityInfo | None:
        """Build a link EntityInfo from a Core ``Table(...)`` call, or None if it
        is not structurally an association table."""
        # Table name is the first positional string arg; fall back to variable name.
        table_name = var_name
        if (
            call.args
            and isinstance(call.args[0], ast.Constant)
            and isinstance(call.args[0].value, str)
        ):
            table_name = call.args[0].value

        fields: List[FieldInfo] = []
        for arg in call.args:
            if self._is_call_to(arg, "Column"):
                field = self._parse_core_column(arg)
                if field is not None:
                    fields.append(field)

        if not self._is_structural_link_table(fields):
            return None

        entity = EntityInfo(
            name=var_name,
            table_name=table_name,
            base_classes=[],
            source="sqlalchemy",
        )
        entity.fields = fields
        entity.is_link_table = True
        return entity

    def _parse_core_column(self, call: ast.Call) -> FieldInfo | None:
        """Parse a Core ``Column("name", <Type>, ForeignKey(...), primary_key=...)``."""
        if not call.args or not isinstance(call.args[0], ast.Constant):
            return None
        col_name = str(call.args[0].value)

        is_primary_key = False
        for keyword in call.keywords:
            if keyword.arg == "primary_key" and isinstance(keyword.value, ast.Constant):
                is_primary_key = bool(keyword.value.value)

        fk_target = self._extract_foreign_key_arg(call)

        # An optional positional column type (e.g. Column("id", Integer, ...)).
        type_str = ""
        for arg in call.args[1:]:
            if isinstance(arg, ast.Name):
                type_str = arg.id
                break
            if isinstance(arg, ast.Attribute):
                type_str = arg.attr
                break

        return FieldInfo(
            name=col_name,
            type_str=type_str,
            is_primary_key=is_primary_key,
            is_foreign_key=fk_target is not None,
            foreign_table=fk_target,
        )

    @staticmethod
    def _is_call_to(value: ast.expr, func_name: str) -> TypeGuard[ast.Call]:
        """Check whether an expression is a call to ``func_name`` (Name or attribute)."""
        if not isinstance(value, ast.Call):
            return False
        func = value.func
        return (isinstance(func, ast.Name) and func.id == func_name) or (
            isinstance(func, ast.Attribute) and func.attr == func_name
        )

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
        if model_kind == "django":
            return self._extract_django_fields(class_node)

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

    def _extract_django_fields(
        self, class_node: ast.ClassDef
    ) -> Tuple[Dict[str, FieldInfo], Dict[str, Tuple[str, str, str]]]:
        """Extract fields and relationships from a Django model.

        Django fields are plain assignments (``name = models.CharField(...)``),
        not annotated. Relationship fields (ForeignKey/OneToOneField/
        ManyToManyField) become relationships; every other ``*Field`` is a column.
        """
        fields: Dict[str, FieldInfo] = {}
        relationships: Dict[str, Tuple[str, str, str]] = {}

        for node in class_node.body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name) or target.id.startswith("_"):
                continue
            if not isinstance(node.value, ast.Call):
                continue

            field_type = self._django_field_type(node.value)
            if field_type is None:
                continue

            name = target.id
            if field_type == "ForeignKey":
                # A ForeignKey is a real `<name>_id` column in the DB; model it as
                # such (like SQLAlchemy) so it renders consistently across sources.
                fk = self._parse_django_fk_column(name, node.value, class_node.name)
                if fk:
                    fields[fk.name] = fk
            elif field_type in DJANGO_RELATIONSHIP_FIELDS:
                rel = self._parse_django_relationship(name, field_type, node.value, class_node.name)
                if rel:
                    relationships[name] = rel
            else:
                fields[name] = self._parse_django_column(name, field_type, node.value)

        return fields, relationships

    def _parse_django_fk_column(
        self, name: str, call: ast.Call, current_class: str
    ) -> FieldInfo | None:
        """Model a Django ``ForeignKey`` as the ``<name>_id`` column it creates in the DB."""
        target = self._resolve_django_relationship_target(call, current_class)
        if target is None:
            return None

        is_nullable = False
        for keyword in call.keywords:
            if keyword.arg == "null" and isinstance(keyword.value, ast.Constant):
                is_nullable = bool(keyword.value.value)

        return FieldInfo(
            name=f"{name}_id",
            type_str=self._django_display_type("BigAutoField"),
            is_foreign_key=True,
            is_nullable=is_nullable,
            foreign_table=f"{self._django_target_table(target)}.id",
        )

    def _django_target_table(self, class_name: str) -> str:
        """Resolve a target class name to its table name (Meta.db_table or snake_case)."""
        node = self.all_classes.get(class_name)
        if node is not None:
            db_table = self._meta_value(node, "db_table")
            if isinstance(db_table, str):
                return db_table
        return self._to_snake_case(class_name)

    @staticmethod
    def _django_field_type(call: ast.Call) -> str | None:
        """Return the Django field class name (e.g. "CharField", "ForeignKey").

        Only constructs that are relationship fields or end in "Field" qualify,
        which filters out non-field assignments such as ``objects = Manager()``.
        """
        func = call.func
        if isinstance(func, ast.Attribute):
            name = func.attr
        elif isinstance(func, ast.Name):
            name = func.id
        else:
            return None
        if name in DJANGO_RELATIONSHIP_FIELDS or name.endswith("Field"):
            return name
        return None

    def _parse_django_column(self, name: str, field_type: str, call: ast.Call) -> FieldInfo:
        """Parse a Django column field (``models.CharField(...)``, etc.)."""
        is_primary_key = False
        is_nullable = False
        default_value = None

        for keyword in call.keywords:
            if keyword.arg == "primary_key" and isinstance(keyword.value, ast.Constant):
                is_primary_key = bool(keyword.value.value)
            elif keyword.arg == "null" and isinstance(keyword.value, ast.Constant):
                is_nullable = bool(keyword.value.value)
            elif keyword.arg == "default" and isinstance(keyword.value, ast.Constant):
                default_value = repr(keyword.value.value)

        # A choices= referencing a TextChoices/IntegerChoices class links the
        # column to that enum; otherwise show the mapped/raw field type.
        choices_enum = self._django_choices_enum(call)
        type_str = choices_enum if choices_enum else self._django_display_type(field_type)

        return FieldInfo(
            name=name,
            type_str=type_str,
            is_primary_key=is_primary_key,
            is_nullable=is_nullable,
            default_value=default_value,
        )

    def _django_choices_enum(self, call: ast.Call) -> str | None:
        """Return the enum class name a ``choices=`` argument references, if any.

        Handles ``choices=Status.choices`` and ``choices=Status``; the name must
        resolve to a known TextChoices/IntegerChoices/Enum class. Inline
        ``choices=[("a", "A"), ...]`` tuples are anonymous and not linked.
        """
        for keyword in call.keywords:
            if keyword.arg != "choices":
                continue
            node = keyword.value
            enum_name = None
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                enum_name = node.value.id  # Status.choices -> Status
            elif isinstance(node, ast.Name):
                enum_name = node.id  # choices=Status
            if (
                enum_name
                and enum_name in self.all_classes
                and self._is_enum_class(self.all_classes[enum_name])
            ):
                return enum_name
        return None

    def _django_display_type(self, field_type: str) -> str:
        """Map a Django field type to a readable Python type.

        Falls back to the original Django field name for ambiguous/unknown fields,
        or always returns it when ``--django-raw-types`` is set.
        """
        if self.django_raw_types:
            return field_type
        return DJANGO_FIELD_TYPE_MAP.get(field_type, field_type)

    def _parse_django_relationship(
        self, name: str, field_type: str, call: ast.Call, current_class: str
    ) -> Tuple[str, str, str] | None:
        """Parse a Django relationship field into a (target, rel_type, attr) tuple.

        ``ManyToManyField(through=...)`` is skipped - that M:N is drawn through
        the through-model's own foreign keys, exactly like SQLAlchemy ``secondary=``.
        """
        target = self._resolve_django_relationship_target(call, current_class)
        if target is None:
            return None

        if field_type == "ManyToManyField":
            if any(keyword.arg == "through" for keyword in call.keywords):
                return None
            rel_type = "many_to_many"
        elif field_type == "OneToOneField":
            rel_type = "one_to_one"
        else:  # ForeignKey
            rel_type = "one"

        return (target, rel_type, name)

    def _resolve_django_relationship_target(self, call: ast.Call, current_class: str) -> str | None:
        """Resolve a relationship field's target from its first positional or ``to=`` arg."""
        if call.args:
            return self._resolve_django_target(call.args[0], current_class)
        for keyword in call.keywords:
            if keyword.arg == "to":
                return self._resolve_django_target(keyword.value, current_class)
        return None

    @staticmethod
    def _resolve_django_target(node: ast.expr, current_class: str) -> str | None:
        """Resolve a Django relationship target to a class name.

        Handles ``"self"``, ``"app.Model"`` / ``"Model"`` string references and a
        direct class reference (``ForeignKey(Author, ...)``).
        """
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value
            if value == "self":
                return current_class
            return value.split(".")[-1]
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return None

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
        """Parse a relationship from an annotated assignment.

        A relationship that declares ``link_model=`` (SQLModel) or ``secondary=``
        (SQLAlchemy) is a many-to-many association already expressed by the link
        table. It must not be emitted as a direct edge - that would duplicate the
        link-table path and misrepresent the cardinality as 1:N - so it is skipped.
        """
        if not isinstance(node.target, ast.Name):
            return None

        if isinstance(node.value, ast.Call) and any(
            kw.arg in ("link_model", "secondary") for kw in node.value.keywords
        ):
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
    django_raw_types: bool = False,
    exclude_paths: List[str] | None = None,
    use_default_excludes: bool = True,
    include_patterns: List[str] | None = None,
    hint_unmatched_model_packages: bool = False,
) -> Tuple[Dict[str, EntityInfo], Dict[str, EnumInfo]]:
    """
    Parse SQLModel, SQLAlchemy, Django, Pydantic and dataclass models in a directory.

    Args:
        path: Path to directory containing model files
        exclude_patterns: List of case-sensitive glob patterns. An entity is
            excluded if a pattern matches its class name or its table name.
        infer_keys: For keyless sources (Pydantic/dataclass), infer a primary
            key from a field named ``id`` and a foreign key from ``<x>_id``.
        sources: Restrict which model kinds become entities (subset of
            ``MODEL_SOURCES``). ``None`` includes all kinds.
        django_raw_types: Show original Django field names (``CharField``)
            instead of mapped Python types (``str``).
        exclude_paths: Case-sensitive globs matched against each ``models.py``
            path (relative to ``path``) or any single path segment; matches are
            skipped before parsing.
        use_default_excludes: Skip ``models.py`` files under known non-project
            directories (venv/site-packages/caches). Set ``False`` to scan them.
        include_patterns: Glob patterns selecting which files are scanned.
            Slash patterns match the path relative to ``path`` (``**`` crosses
            dirs); slashless patterns match a basename at any depth. Defaults to
            ``["models.py"]``.

    Returns:
        Tuple of (entities dict, enums dict)
    """
    parser = ASTDatabaseParser(
        path,
        exclude_patterns=exclude_patterns,
        infer_keys=infer_keys,
        sources=sources,
        django_raw_types=django_raw_types,
        exclude_paths=exclude_paths,
        use_default_excludes=use_default_excludes,
        include_patterns=include_patterns,
        hint_unmatched_model_packages=hint_unmatched_model_packages,
    )
    return parser.parse_all_models()
