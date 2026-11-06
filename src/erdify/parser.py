"""AST-based parser for SQLModel, SQLAlchemy, Django, Pydantic and dataclass models."""

import ast
import os
import re
import sys
from dataclasses import dataclass, replace
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Dict, List, Mapping, Tuple, TypeGuard, TypeVar

from .config import EntityInfo, EnumInfo, FieldInfo, is_structural_link_table


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

_V = TypeVar("_V")

# A relationship while parsing: (target, type, attribute, nullable). The
# public EntityInfo.relationships keeps (target, type, attribute); the flag
# goes to EntityInfo.nullable_relationships.
_Rel = Tuple[str, str, str, bool]

# A class body's (fields, relationships, declared attribute names).
_ClassMembers = Tuple[Dict[str, FieldInfo], Dict[str, _Rel], List[str]]

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


class ModelParseError(Exception):
    """Raised in strict mode when one or more input files could not be parsed.

    Attributes:
        errors: ``(file, message)`` for every file that failed, in scan order.
    """

    def __init__(self, errors: List[Tuple[Path, str]]):
        self.errors = errors
        files = ", ".join(str(path) for path, _ in errors)
        super().__init__(f"{len(errors)} file(s) could not be parsed (strict mode): {files}")


class ASTDatabaseParser:
    """Parses database models using AST to extract schema information.

    Handles Python model files only; use :func:`parse_models_directory` for
    SQL DDL or mixed input.

    Public API: the constructor and :meth:`parse_all_models`. Every other
    attribute and method is internal and may change in any release.

    Args:
        database_path: Directory to scan for model files.
        exclude_patterns: Case-sensitive globs; an entity is dropped if one
            matches its class name or table name.
        infer_keys: For keyless sources (Pydantic/dataclass), infer a primary
            key from ``id`` and a foreign key from ``<x>_id``.
        sources: Restrict which model kinds become entities (subset of
            ``MODEL_SOURCES``). ``None`` includes all kinds.
        django_raw_types: Show Django field names (``CharField``) instead of
            mapped Python types (``str``).
        exclude_paths: Case-sensitive globs matched against each file path
            (relative to ``database_path``) or any path segment.
        use_default_excludes: Skip ``DEFAULT_EXCLUDE_DIRS`` (venv,
            site-packages, caches) during the walk.
        include_patterns: Globs selecting which files are scanned. Defaults to
            ``["models.py"]``.
        hint_unmatched_model_packages: Warn once on stderr about a ``models/``
            package the include patterns skip.
        base_classes: Extra base-class names to treat as Pydantic models.
        strict: Raise :class:`ModelParseError` if any file fails to parse,
            instead of reporting it on stderr and skipping it.
    """

    def __init__(
        self,
        database_path: Path,
        *,
        exclude_patterns: List[str] | None = None,
        infer_keys: bool = False,
        sources: List[str] | None = None,
        django_raw_types: bool = False,
        exclude_paths: List[str] | None = None,
        use_default_excludes: bool = True,
        include_patterns: List[str] | None = None,
        hint_unmatched_model_packages: bool = False,
        base_classes: List[str] | None = None,
        strict: bool = False,
    ):
        self.database_path = database_path
        self.strict = strict
        #: (file, message) for every file that failed to parse in the last run.
        self._parse_errors: List[Tuple[Path, str]] = []
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
        #: Number of .py/.sql files seen during the last discovery walk, after
        #: directory pruning. This is the population --include selects from;
        #: the CLI reports it when a run produces no entities.
        self._candidate_file_count = 0
        #: Extra base-class names to treat as Pydantic models. Pydantic detection
        #: resolves ancestors only across the scanned files, so a base defined in
        #: an installed package (``ninja.Schema``) or an unscanned internal library
        #: is invisible; naming it here closes that gap.
        self.base_classes = set(base_classes) if base_classes else set()
        #: Restrict which model kinds become entities; None = all of MODEL_SOURCES.
        self.sources = set(sources) if sources else None
        self._entities: Dict[str, EntityInfo] = {}
        self._enums: Dict[str, EnumInfo] = {}
        self._all_classes: Dict[str, ast.ClassDef] = {}  # Store all class definitions
        self._mro_cache: Dict[str, List[str] | None] = {}
        self._target_column_cache: Dict[Tuple[str, str | None], Tuple[str, str]] = {}
        self._dataclass_cache: Dict[str, Tuple[Dict[str, FieldInfo], Dict[str, _Rel]]] = {}
        self._file_trees: Dict[Path, ast.Module] = {}

    def parse_all_models(self) -> Tuple[Dict[str, EntityInfo], Dict[str, EnumInfo]]:
        """Parse all model files under ``database_path``.

        Returns:
            Tuple of (entities, enums), both keyed by class name.

        Raises:
            ModelParseError: ``strict`` is set and at least one file failed to
                parse. Every failure is still reported on stderr first.
        """
        model_files = self._discover_model_files()
        self._parse_errors = []

        # First pass: parse all files and collect class definitions
        for model_file in model_files:
            try:
                with open(model_file, encoding="utf-8") as f:  # PEP 3120 default
                    content = f.read()
                tree = ast.parse(content)
                self._file_trees[model_file] = tree

                # Collect all class definitions
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef):
                        self._all_classes[node.name] = node
            except Exception as e:
                print(f"Error parsing {model_file}: {e}", file=sys.stderr)
                self._parse_errors.append((model_file, str(e)))

        if self.strict and self._parse_errors:
            raise ModelParseError(self._parse_errors)

        # Second pass: process enum and model classes
        self._mro_cache = {}
        self._target_column_cache = {}
        self._dataclass_cache = {}
        for class_node in self._all_classes.values():
            if self._is_enum_class(class_node):
                self._parse_enum_class(class_node)
                continue
            source = self._classify_source(class_node)
            if source is not None and (self.sources is None or source in self.sources):
                derived = self._model_derived_schema(class_node) if source == "pydantic" else None
                if derived is not None:
                    holder, target = derived
                    print(
                        f"Warning: skipped {class_node.name} - its fields come from "
                        f"{holder}.model ({target}), which erdify does not resolve. "
                        "Drawing it would add an entity with no fields. "
                        "See https://github.com/devsuit-berlin/erdify/issues/171",
                        file=sys.stderr,
                    )
                    continue
                self._parse_table_class(class_node, source)

        # Synthesize link entities from module-level Core Table(...) association
        # tables referenced by relationship(secondary=...) (#34).
        self._parse_core_association_tables()

        # Third pass: apply exclude patterns
        self._apply_exclude_patterns()

        return self._entities, self._enums

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
        model_packages: List[Path] = []
        self._candidate_file_count = 0
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
                model_packages.append(dpath)
            for filename in filenames:
                if filename.endswith((".py", ".sql")):
                    self._candidate_file_count += 1
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
        # Only hint about packages whose files the current include patterns did
        # not already pick up; otherwise the "was not scanned" message is false.
        selected_dirs = {p.parent for p in found}
        self._unmatched_model_packages = [p for p in model_packages if p not in selected_dirs]
        if self._unmatched_model_packages:
            example = sorted(self._unmatched_model_packages)[0]
            try:
                example_str = example.relative_to(self.database_path).as_posix()
            except ValueError:
                example_str = example.as_posix()
            print(
                f"Hint: found a models/ package ({example_str}) that was not scanned "
                f"(the default only matches models.py). Use "
                f"--include '**/models/*.py' to include it.",
                file=sys.stderr,
            )
        return sorted(found)

    def _is_path_excluded(self, model_file: Path) -> bool:
        """Decide whether a discovered model file should be skipped before parsing.

        Skips files under a default non-project directory (venv/site-packages/
        caches, unless disabled) or matching an ``exclude_paths`` glob against the
        path relative to the input or any single path segment.
        """
        try:
            rel = model_file.relative_to(self.database_path).as_posix()
        except ValueError:
            rel = model_file.as_posix()
        segments = rel.split("/")[:-1]  # directory segments only (drop the filename)

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

        excluded_names = {name for name, e in self._entities.items() if is_excluded(e)}

        self._entities = {
            name: e for name, e in self._entities.items() if name not in excluded_names
        }

        for entity in self._entities.values():
            entity.relationships = [
                rel for rel in entity.relationships if rel[0] not in excluded_names
            ]
            kept = {attr for _, _, attr in entity.relationships}
            entity.nullable_relationships = [
                attr for attr in entity.nullable_relationships if attr in kept
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
            self._enums[class_node.name] = EnumInfo(name=class_node.name, values=values)

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

    def _model_derived_schema(self, class_node: ast.ClassDef) -> Tuple[str, str] | None:
        """Detect a ninja-style ``ModelSchema`` and report where its fields come from.

        django-ninja's ``ModelSchema`` (inner ``Meta``) and ninja-schema's
        (inner ``Config``) take their fields from a Django model named in that
        inner class rather than from the class body. erdify cannot resolve the
        reference, so the entity would be drawn with no fields at all — worse
        than not drawing it. Detection is deliberately narrow: only an inner
        ``Meta``/``Config`` that assigns ``model`` counts, so an ordinary
        Pydantic model with a nested config class is untouched.

        Returns:
            ``(holder, target)`` where *holder* is ``"Meta"`` or ``"Config"``
            and *target* is the referenced model's name, or ``None`` when the
            class is not a model-derived schema.
        """
        for node in class_node.body:
            if not isinstance(node, ast.ClassDef) or node.name not in ("Meta", "Config"):
                continue
            for inner in node.body:
                if not isinstance(inner, ast.Assign):
                    continue
                for target in inner.targets:
                    if not (isinstance(target, ast.Name) and target.id == "model"):
                        continue
                    value = inner.value
                    if isinstance(value, ast.Name):
                        return node.name, value.id
                    if isinstance(value, ast.Attribute):
                        return node.name, value.attr
                    if isinstance(value, ast.Call):
                        return node.name, "unresolved"
                    return node.name, "unresolved"
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
                ancestor = self._all_classes.get(base.id)
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
        """Check if a class inherits from Pydantic's BaseModel, directly or via ancestors.

        Any name in ``self.base_classes`` counts as well, which is how a base
        defined outside the scanned files (``ninja.Schema``, a shared internal
        ``BaseSchema``) can be recognised at all.
        """
        visited = visited if visited is not None else set()
        if class_node.name in visited:
            return False
        visited.add(class_node.name)

        for base in class_node.bases:
            if isinstance(base, ast.Name):
                if base.id == "BaseModel" or base.id in self.base_classes:
                    return True
                ancestor = self._all_classes.get(base.id)
                if ancestor is not None and self._inherits_basemodel(ancestor, visited):
                    return True
            elif isinstance(base, ast.Attribute):
                if base.attr == "BaseModel" or base.attr in self.base_classes:
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
        relationships_dict: Dict[str, _Rel] = {}

        # Recursively collect fields from all ancestors
        base_fields, base_rels = self._collect_fields(class_node, source)
        fields_dict.update(base_fields)
        relationships_dict.update(base_rels)

        entity.fields = list(fields_dict.values())
        entity.relationships = [(t, kind, attr) for t, kind, attr, _ in relationships_dict.values()]
        entity.nullable_relationships = [
            attr for _, _, attr, nullable in relationships_dict.values() if nullable
        ]

        # Single-column UniqueConstraint / unique Index in __table_args__ (#218).
        # Constraints name the *database* column, which mapped_column("col", ...)
        # may set apart from the attribute name (#221).
        # A string names the DB column; a bare reference names the attribute.
        unique_cols, unique_refs = self._table_args_unique_columns(class_node)
        db_names = self._db_column_names(class_node)
        for f in entity.fields:
            if f.is_primary_key:
                continue
            if db_names.get(f.name, f.name) in unique_cols or f.name in unique_refs:
                f.is_unique = True

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

        # Detect join tables structurally: an entity whose composite primary
        # key is made up entirely of foreign keys (with no payload columns) is
        # an association table regardless of its class name (#35, #118).
        entity.is_link_table = self._is_structural_link_table(entity.fields)

        self._entities[class_node.name] = entity

    _is_structural_link_table = staticmethod(is_structural_link_table)

    def _db_column_names(self, class_node: ast.ClassDef) -> Dict[str, str]:
        """Map attribute name -> explicit DB column name for a class and its bases.

        See :meth:`_explicit_column_name` for the recognized forms. A column
        without an explicit name maps to itself, so a redeclaration without one
        overrides an inherited name. Bases resolve in the same order as the
        fields (:meth:`_merge_order`), so the name matches the winning column.
        """
        names: Dict[str, str] = {}
        for class_name in self._merge_order(class_node):
            for node in self._all_classes[class_name].body:
                if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    db_name = self._explicit_column_name(node.value)
                    names[node.target.id] = db_name if db_name is not None else node.target.id
        return names

    @classmethod
    def _explicit_column_name(cls, value: ast.expr | None) -> str | None:
        """Return the name a string constraint uses for this column, if explicit.

        Recognizes ``mapped_column("name", ...)`` / ``mapped_column(name="name")``,
        and SQLModel's ``Field(sa_column=Column("name", ...))`` /
        ``Field(sa_column_kwargs={"name": "name"})``. SQLAlchemy resolves a
        constraint's string column through the column *key*, which defaults to
        the name, so an explicit ``key=`` takes precedence.
        """
        if value is None:
            return None
        if cls._is_call_to(value, "mapped_column") or cls._is_call_to(value, "Column"):
            for kw in value.keywords:
                if (
                    kw.arg == "key"
                    and isinstance(kw.value, ast.Constant)
                    and isinstance(kw.value.value, str)
                ):
                    return kw.value.value
            if (
                value.args
                and isinstance(value.args[0], ast.Constant)
                and isinstance(value.args[0].value, str)
            ):
                return value.args[0].value
            for kw in value.keywords:
                if (
                    kw.arg == "name"
                    and isinstance(kw.value, ast.Constant)
                    and isinstance(kw.value.value, str)
                ):
                    return kw.value.value
            return None
        if cls._is_call_to(value, "Field"):
            for kw in value.keywords:
                if kw.arg == "sa_column":
                    return cls._explicit_column_name(kw.value)
                if kw.arg == "sa_column_kwargs" and isinstance(kw.value, ast.Dict):
                    opts = {
                        key.value: val.value
                        for key, val in zip(kw.value.keys, kw.value.values)
                        if isinstance(key, ast.Constant)
                        and isinstance(val, ast.Constant)
                        and isinstance(val.value, str)
                    }
                    # As above: an explicit key wins over the name.
                    found = opts.get("key", opts.get("name"))
                    if isinstance(found, str):
                        return found
        return None

    @classmethod
    def _table_args_unique_columns(cls, class_node: ast.ClassDef) -> Tuple[set[str], set[str]]:
        """Columns made unique on their own by the class's ``__table_args__``.

        Recognizes ``UniqueConstraint("col")`` and ``Index("name", "col",
        unique=True)`` with exactly one column, in a tuple/list ``__table_args__``
        (a trailing options dict is ignored). Composite constraints and partial
        indexes (``*_where=``) do not make a column unique and are skipped.

        Returns ``(db_columns, attribute_refs)``: a string names the *database*
        column, while a bare reference (``UniqueConstraint(account_id)``) names
        the attribute declared earlier in the class body.
        """
        value: ast.expr | None = None
        for node in class_node.body:
            if isinstance(node, ast.Assign):
                if any(isinstance(t, ast.Name) and t.id == "__table_args__" for t in node.targets):
                    value = node.value
            elif (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id == "__table_args__"
            ):
                value = node.value
        columns: set[str] = set()
        refs: set[str] = set()
        if not isinstance(value, (ast.Tuple, ast.List)):
            return columns, refs

        for item in value.elts:
            if cls._is_call_to(item, "UniqueConstraint"):
                cols = item.args
            elif cls._is_call_to(item, "Index"):
                if not any(
                    kw.arg == "unique" and isinstance(kw.value, ast.Constant) and kw.value.value
                    for kw in item.keywords
                ):
                    continue
                # A partial index (postgresql_where=, sqlite_where=, ...) is only
                # unique over a subset of rows, so it does not imply a 1:1. A
                # literal `*_where=None` is "no predicate", i.e. not partial.
                if any(
                    kw.arg
                    and kw.arg.endswith("_where")
                    and not (isinstance(kw.value, ast.Constant) and kw.value.value is None)
                    for kw in item.keywords
                ):
                    continue
                cols = item.args[1:]  # first positional arg is the index name
            else:
                continue
            if len(cols) == 1:
                col = cols[0]
                if isinstance(col, ast.Constant) and isinstance(col.value, str):
                    columns.add(col.value)
                elif isinstance(col, ast.Name):
                    refs.add(col.id)
        return columns, refs

    def _parse_core_association_tables(self) -> None:
        """Synthesize link entities from module-level Core ``Table(...)`` assignments.

        ``relationship(secondary=Table(...))`` points at a SQLAlchemy Core table
        rather than a mapped class. Only class definitions become entities in the
        normal passes, so such association tables - and their M:N - would be lost.
        Parse module-level ``name = Table("t", metadata, Column(...), ...)``
        assignments that are structurally association tables (a composite PK
        made up entirely of FK columns) and add them as link entities (#34).
        """
        if self.sources is not None and "sqlalchemy" not in self.sources:
            return

        for tree in self._file_trees.values():
            for node in tree.body:
                if not isinstance(node, ast.Assign):
                    continue
                if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                    continue
                if not self._is_call_to(node.value, "Table"):
                    continue

                var_name = node.targets[0].id
                entity = self._build_core_table_entity(var_name, node.value)
                if entity is not None and entity.name not in self._entities:
                    self._entities[entity.name] = entity

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

    def _local_bases(self, class_node: ast.ClassDef) -> List[str]:
        """Names of the direct bases that are classes parsed from the input."""
        return [
            base.id
            for base in class_node.bases
            if isinstance(base, ast.Name) and base.id in self._all_classes
        ]

    def _dfs_order(self, class_node: ast.ClassDef, visited: set[str]) -> List[str]:
        """Classes in depth-first post-order: bases (left to right), then the class.

        Each class appears once. This is the order fields are listed in.
        """
        if class_node.name in visited:
            return []
        visited.add(class_node.name)
        order: List[str] = []
        for base in self._local_bases(class_node):
            order.extend(self._dfs_order(self._all_classes[base], visited))
        order.append(class_node.name)
        return order

    def _mro(self, name: str, stack: Tuple[str, ...] = ()) -> List[str] | None:
        """C3 linearization of a parsed class, like Python's ``__mro__``.

        Bases outside the parsed files are ignored. Returns None when Python
        would reject the hierarchy (no consistent order) or it is cyclic, e.g.
        ``class User(User)`` extending a namesake.
        """
        if name in self._mro_cache:
            return self._mro_cache[name]
        if name in stack:
            return None
        bases = self._local_bases(self._all_classes[name])
        seqs: List[List[str]] = []
        for base in bases:
            base_mro = self._mro(base, stack + (name,))
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

    def _merge_order(self, class_node: ast.ClassDef) -> List[str]:
        """Classes to merge members from, where a later class overrides an earlier one.

        This is the reversed MRO, so the class body wins over its bases and an
        earlier base wins over a later one, as in Python (#228). Without a valid
        MRO it falls back to :meth:`_dfs_order`.
        """
        mro = self._mro(class_node.name)
        if mro is None:
            return self._dfs_order(class_node, set())
        return mro[::-1]

    def _collect_fields(
        self, class_node: ast.ClassDef, model_kind: str
    ) -> Tuple[Dict[str, FieldInfo], Dict[str, _Rel]]:
        """Collect the fields and relationships of a class and all its ancestors.

        Which declaration of an attribute wins follows the MRO
        (:meth:`_merge_order`), or, for dataclasses, the dataclass field
        merge (:meth:`_dataclass_fields`). The order they are listed in is the
        one the pre-MRO merge produced (:meth:`_listing_order`), so resolving by
        MRO does not reorder the output.
        """
        dfs_order = self._dfs_order(class_node, set())
        merge_order = self._merge_order(class_node)
        members = {
            name: self._class_members(
                self._all_classes[name],
                model_kind,
                self._django_self_owner(name, merge_order) if model_kind == "django" else None,
            )
            for name in dfs_order
        }
        order_fields, order_rels = self._listing_order(class_node, set(), members, model_kind)
        if model_kind == "dataclass" and self._mro(class_node.name) is not None:
            fields, rels = self._dataclass_fields(class_node.name, members)
        else:
            fields, rels = self._merge_members(merge_order, members, model_kind)
        return self._reorder(fields, order_fields), self._reorder(rels, order_rels)

    def _django_self_owner(self, name: str, merge_order: List[str]) -> str:
        """The model a Django ``"self"`` relation declared in class ``name`` points at.

        A concrete model's own fields point at that model, also when a child
        inherits them (multi-table inheritance). An abstract base's or a plain
        mixin's fields are copied into the first concrete model that inherits
        it, so ``"self"`` points there (#226).
        """
        if self._is_concrete_django_model(name):
            return name
        for candidate in merge_order:  # root first, so the nearest concrete heir wins
            if (
                candidate != name
                and self._is_concrete_django_model(candidate)
                and name in (self._mro(candidate) or ())
            ):
                return candidate
        return name

    def _is_concrete_django_model(self, name: str) -> bool:
        """A Django model with its own table: a ``models.Model`` subclass, not abstract.

        A plain mixin or an abstract base has no table, so a ``"self"``
        relation declared there belongs to the concrete model that copies it.
        """
        node = self._all_classes[name]
        return self._inherits_django_model(node) and not self._meta_flag(node, "abstract")

    def _dataclass_fields(
        self, name: str, members: Dict[str, _ClassMembers]
    ) -> Tuple[Dict[str, FieldInfo], Dict[str, _Rel]]:
        """The members of a dataclass entity: ``dataclasses.fields()`` plus mixins.

        First the stdlib result (:meth:`_effective_dataclass_fields`). Then
        annotations of undecorated mixins in the hierarchy, which the stdlib
        ignores but erdify has always shown, fill in only attributes no
        dataclass declares (the first such mixin in the MRO wins).
        """
        fields, rels = self._effective_dataclass_fields(name, members)
        # The cache is shared across entities, and _parse_table_class mutates
        # fields (e.g. is_unique), so each entity gets its own copies.
        fields, rels = {attr: replace(f) for attr, f in fields.items()}, dict(rels)
        for base in self._mro(name) or [name]:
            if self._is_dataclass(self._all_classes[base]):
                continue
            base_fields, base_rels, _ = members[base]
            for attr, field in base_fields.items():
                if attr not in fields and attr not in rels:
                    fields[attr] = replace(field)
            for attr, rel in base_rels.items():
                if attr not in fields and attr not in rels:
                    rels[attr] = rel
        return fields, rels

    def _effective_dataclass_fields(
        self, name: str, members: Dict[str, _ClassMembers]
    ) -> Tuple[Dict[str, FieldInfo], Dict[str, _Rel]]:
        """A class's ``__dataclass_fields__``, as the stdlib computes it.

        A decorated class merges each base's ``__dataclass_fields__`` in
        reversed MRO, then its own annotations. So in ``Child(Left, Middle)``
        an attribute ``Left`` merely inherits still overrides one ``Middle``
        redeclares. An undecorated class has no fields of its own: it exposes
        those of the first decorated class in its MRO. Cached per parse; a
        class's own members do not depend on the entity being built.
        """
        memo = self._dataclass_cache
        if name in memo:
            return memo[name]
        mro = self._mro(name) or [name]
        if not self._is_dataclass(self._all_classes[name]):
            owner = next((c for c in mro if self._is_dataclass(self._all_classes[c])), None)
            result = (
                self._effective_dataclass_fields(owner, members) if owner is not None else ({}, {})
            )
            memo[name] = result
            return result
        synthetic: Dict[str, _ClassMembers] = {}
        for base in mro[:0:-1]:
            base_fields, base_rels = self._effective_dataclass_fields(base, members)
            synthetic[base] = (base_fields, base_rels, [*base_fields, *base_rels])
        synthetic[name] = members[name]
        result = self._merge_members([*mro[:0:-1], name], synthetic, "dataclass")
        memo[name] = result
        return result

    @staticmethod
    def _drop_django_redeclared(
        fields: Dict[str, FieldInfo], rels: Dict[str, _Rel], attr: str
    ) -> None:
        """Drop whatever earlier classes stored for a redeclared Django attribute.

        A Django attribute is stored under a key that depends on its kind
        (relationship ``owner`` vs. FK column ``owner_id``, #224), so all of
        them go.
        """
        rels.pop(attr, None)
        fields.pop(attr, None)
        inherited_fk = fields.get(f"{attr}_id")
        if inherited_fk is not None and inherited_fk.is_foreign_key:
            del fields[f"{attr}_id"]

    def _listing_order(
        self,
        class_node: ast.ClassDef,
        visited: set[str],
        members: Dict[str, _ClassMembers],
        model_kind: str,
    ) -> Tuple[Dict[str, FieldInfo], Dict[str, _Rel]]:
        """The keys, in listing order, of the recursive merge used before #228.

        Each base's whole subtree is merged in (left to right, each class once),
        then the class body. Only a Django body's own redeclaration moves an
        inherited attribute to the body's position; a sibling base never
        displaces another sibling's attribute. Only the key order is used.
        """
        fields: Dict[str, FieldInfo] = {}
        rels: Dict[str, _Rel] = {}
        if class_node.name in visited:
            return fields, rels
        visited.add(class_node.name)
        for base in self._local_bases(class_node):
            base_fields, base_rels = self._listing_order(
                self._all_classes[base], visited, members, model_kind
            )
            fields.update(base_fields)
            rels.update(base_rels)
        class_fields, class_rels, declared = members[class_node.name]
        if model_kind == "django":
            for attr in declared:
                self._drop_django_redeclared(fields, rels, attr)
        fields.update(class_fields)
        rels.update(class_rels)
        return fields, rels

    @staticmethod
    def _reorder(values: Dict[str, _V], order: Mapping[str, object]) -> Dict[str, _V]:
        """Return ``values`` with keys in ``order``'s key order, extra keys last."""
        result = {key: values[key] for key in order if key in values}
        result.update((key, value) for key, value in values.items() if key not in result)
        return result

    def _class_members(
        self, class_node: ast.ClassDef, model_kind: str, concrete: str | None = None
    ) -> _ClassMembers:
        """A single class body's fields, relationships, and declared attribute names."""
        fields, rels = self._extract_class_fields(class_node, model_kind, concrete)
        if model_kind == "django":
            declared = self._django_declared_names(class_node)
        else:
            declared = [*fields, *rels]
        return fields, rels, declared

    @staticmethod
    def _merge_members(
        order: List[str], members: Dict[str, _ClassMembers], model_kind: str
    ) -> Tuple[Dict[str, FieldInfo], Dict[str, _Rel]]:
        """Merge class members in ``order``; a later class overrides an earlier one.

        A redeclared attribute replaces whatever an earlier class stored for it,
        even under another key or kind: a Django relationship ``owner`` vs. its
        FK column ``owner_id`` (#224), or a column vs. a model reference.
        """
        fields: Dict[str, FieldInfo] = {}
        rels: Dict[str, _Rel] = {}
        for class_name in order:
            class_fields, class_rels, declared = members[class_name]
            for attr in declared:
                if model_kind == "django":
                    ASTDatabaseParser._drop_django_redeclared(fields, rels, attr)
                # Same key and kind: update() below replaces it in place.
                elif attr in class_fields:
                    rels.pop(attr, None)
                else:
                    fields.pop(attr, None)
            fields.update(class_fields)
            rels.update(class_rels)
        return fields, rels

    def _django_declared_names(self, class_node: ast.ClassDef) -> List[str]:
        """Attribute names a Django model body declares or removes.

        A model field declares its name. ``name = None`` removes a field
        inherited from an abstract base, as Django documents, so it also drops
        whatever the bases stored under that name.
        """
        return [
            *(name for name, _, _ in self._django_field_calls(class_node)),
            *self._django_removed_names(class_node),
        ]

    @staticmethod
    def _django_removed_names(class_node: ast.ClassDef) -> List[str]:
        """Names a Django class body sets to ``None`` to remove an inherited field."""
        return [
            node.targets[0].id
            for node in class_node.body
            if isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant)
            and node.value.value is None
        ]

    def _extract_class_fields(
        self, class_node: ast.ClassDef, model_kind: str, concrete: str | None = None
    ) -> Tuple[Dict[str, FieldInfo], Dict[str, _Rel]]:
        """Extract fields and relationships from a class definition.

        ``concrete`` (Django only, default: the class itself) is the model a
        ``"self"`` relation in this body points at (:meth:`_django_self_owner`).
        """
        if model_kind == "django":
            return self._extract_django_fields(class_node, concrete or class_node.name)

        fields: Dict[str, FieldInfo] = {}
        relationships: Dict[str, _Rel] = {}

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
        self, class_node: ast.ClassDef, concrete: str
    ) -> Tuple[Dict[str, FieldInfo], Dict[str, _Rel]]:
        """Extract fields and relationships from a Django model.

        Django fields are plain assignments (``name = models.CharField(...)``),
        not annotated. ``ForeignKey`` / ``OneToOneField`` become ``<name>_id``
        foreign-key columns, ``ManyToManyField`` becomes a relationship, and
        every other ``*Field`` is a column. ``"self"`` names ``concrete``, the
        model being built, as in Django, where a relation to ``"self"`` in an
        abstract base points at each concrete subclass.
        """
        fields: Dict[str, FieldInfo] = {}
        relationships: Dict[str, _Rel] = {}

        for name, field_type, call in self._django_field_calls(class_node):
            if field_type in ("ForeignKey", "OneToOneField"):
                # Both are a real `<name>_id` column in the DB; model them as such
                # (like SQLAlchemy) so they render consistently across sources and
                # follow `null=` (#223). A OneToOneField is that column made unique,
                # or the PK itself with primary_key=True (shared primary key), in
                # which case Django adds no implicit `id` (#224).
                fk = self._parse_django_fk_column(
                    name, call, concrete, one_to_one=field_type == "OneToOneField"
                )
                if fk:
                    fields[fk.name] = fk
            elif field_type == "ManyToManyField":
                rel = self._parse_django_many_to_many(name, call, concrete)
                if rel:
                    relationships[name] = rel
            else:
                fields[name] = self._parse_django_column(name, field_type, call)

        return fields, relationships

    def _django_field_calls(self, class_node: ast.ClassDef) -> List[Tuple[str, str, ast.Call]]:
        """``(attribute, field class name, call)`` for each model field in a Django class body."""
        calls: List[Tuple[str, str, ast.Call]] = []
        for node in class_node.body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name) or target.id.startswith("_"):
                continue
            if not isinstance(node.value, ast.Call):
                continue
            field_type = self._django_field_type(node.value)
            if field_type is not None:
                calls.append((target.id, field_type, node.value))
        return calls

    @staticmethod
    def _has_true_kw(call: ast.Call, name: str) -> bool:
        """Whether ``call`` passes ``name=True`` as a literal keyword."""
        return any(
            kw.arg == name and isinstance(kw.value, ast.Constant) and kw.value.value is True
            for kw in call.keywords
        )

    def _parse_django_fk_column(
        self, name: str, call: ast.Call, current_class: str, *, one_to_one: bool = False
    ) -> FieldInfo | None:
        """Model a ``ForeignKey`` / ``OneToOneField`` as the ``<name>_id`` column it creates.

        A ``OneToOneField`` is a ``ForeignKey(unique=True)``.
        """
        target = self._resolve_django_relationship_target(call, current_class)
        if target is None:
            return None

        is_nullable = False
        is_unique = one_to_one
        is_primary_key = False
        for keyword in call.keywords:
            if not isinstance(keyword.value, ast.Constant):
                continue
            if keyword.arg == "null":
                is_nullable = bool(keyword.value.value)
            elif keyword.arg == "unique" and not one_to_one:
                is_unique = bool(keyword.value.value)
            elif keyword.arg == "primary_key":
                is_primary_key = bool(keyword.value.value)

        # ForeignKey(primary_key=True) makes `<name>_id` the table's primary key,
        # so Django adds no implicit `id` (#224). A PK is never NULL, and its
        # uniqueness is tracked by is_primary_key, not is_unique.
        to_field = self._django_to_field(call)
        column, type_str = self._django_target_column(target, to_field, ())
        return FieldInfo(
            name=f"{name}_id",
            type_str=type_str,
            is_primary_key=is_primary_key,
            is_foreign_key=True,
            is_nullable=is_nullable and not is_primary_key,
            is_unique=is_unique and not is_primary_key,
            foreign_table=f"{self._django_target_table(target)}.{column}",
        )

    @staticmethod
    def _django_to_field(call: ast.Call) -> str | None:
        """The literal ``to_field=`` of a Django relationship field, if any."""
        for kw in call.keywords:
            if (
                kw.arg == "to_field"
                and isinstance(kw.value, ast.Constant)
                and isinstance(kw.value.value, str)
            ):
                return kw.value.value
        return None

    def _django_target_column(
        self, target: str, to_field: str | None, stack: Tuple[Tuple[str, str | None], ...]
    ) -> Tuple[str, str]:
        """Return the ``(column, type)`` a Django FK to ``target`` references (#226).

        That is the ``to_field`` column if given, else the target's primary key,
        including one inherited from a base. A key that is itself a foreign key
        is its ``<name>_id`` column, typed like the column *it* references. An
        unknown target, field or cycle falls back to ``id`` / ``to_field`` with
        Django's default ``BigAutoField`` type. A cycle is a repeated
        ``(model, to_field)`` lookup, so following a key to another column of
        the same model still resolves.
        """
        key = (target, to_field)
        cached = self._target_column_cache.get(key)
        if cached is not None:
            return cached
        default = (to_field or "id", self._django_display_type("BigAutoField"))
        node = self._all_classes.get(target)
        if node is None or key in stack:
            return default
        result = self._resolve_django_target_column(target, node, to_field, stack, default)
        self._target_column_cache[key] = result
        return result

    def _resolve_django_target_column(
        self,
        target: str,
        node: ast.ClassDef,
        to_field: str | None,
        stack: Tuple[Tuple[str, str | None], ...],
        default: Tuple[str, str],
    ) -> Tuple[str, str]:
        """Uncached body of :meth:`_django_target_column`."""

        # The winning declaration of each attribute, resolved like the fields (#228).
        declared: Dict[str, Tuple[str, ast.Call, str]] = {}
        for class_name in self._merge_order(node):
            class_node = self._all_classes[class_name]
            for attr in self._django_removed_names(class_node):
                declared.pop(attr, None)
            for attr, field_type, call in self._django_field_calls(class_node):
                declared.pop(attr, None)
                declared[attr] = (field_type, call, class_name)

        if to_field is not None:
            attr = to_field
            # Django also accepts a relation's attname (`account_id` for `account`).
            if attr not in declared and attr.endswith("_id"):
                relation = declared.get(attr[: -len("_id")])
                if relation is not None and relation[0] in ("ForeignKey", "OneToOneField"):
                    attr = attr[: -len("_id")]
            if attr not in declared:
                return default
        else:
            pks = [
                a for a, (_, call, _) in declared.items() if self._has_true_kw(call, "primary_key")
            ]
            if not pks:
                return default
            attr = pks[-1]

        field_type, call, declaring = declared[attr]
        if field_type in ("ForeignKey", "OneToOneField"):
            # "self" binds like on the entity side (#226).
            owner = self._django_self_owner(declaring, self._merge_order(node))
            ref = self._resolve_django_relationship_target(call, owner)
            if ref is None:
                return f"{attr}_id", default[1]
            _, ref_type = self._django_target_column(
                ref, self._django_to_field(call), stack + ((target, to_field),)
            )
            return f"{attr}_id", ref_type
        return attr, self._parse_django_column(attr, field_type, call).type_str

    def _django_target_table(self, class_name: str) -> str:
        """Resolve a target class name to its table name (Meta.db_table or snake_case)."""
        node = self._all_classes.get(class_name)
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
        is_unique = False
        default_value = None

        for keyword in call.keywords:
            if keyword.arg == "primary_key" and isinstance(keyword.value, ast.Constant):
                is_primary_key = bool(keyword.value.value)
            elif keyword.arg == "null" and isinstance(keyword.value, ast.Constant):
                is_nullable = bool(keyword.value.value)
            elif keyword.arg == "unique" and isinstance(keyword.value, ast.Constant):
                is_unique = bool(keyword.value.value)
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
            is_nullable=is_nullable and not is_primary_key,
            default_value=default_value,
            is_unique=is_unique and not is_primary_key,
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
                and enum_name in self._all_classes
                and self._is_enum_class(self._all_classes[enum_name])
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

    def _parse_django_many_to_many(
        self, name: str, call: ast.Call, current_class: str
    ) -> _Rel | None:
        """Parse a Django ``ManyToManyField`` into a relationship tuple.

        ``ForeignKey`` / ``OneToOneField`` are FK columns instead (see
        :meth:`_parse_django_fk_column`). ``ManyToManyField(through=...)`` is
        skipped - that M:N is drawn through the through-model's own foreign
        keys, exactly like SQLAlchemy ``secondary=``.
        """
        target = self._resolve_django_relationship_target(call, current_class)
        if target is None:
            return None
        if any(keyword.arg == "through" for keyword in call.keywords):
            return None
        return (target, "many_to_many", name, False)

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
        is_unique = False

        if node.value and isinstance(node.value, ast.Call):
            # Field() (SQLModel) / mapped_column() (SQLAlchemy), bare or qualified
            # (e.g. orm.mapped_column).
            if self._is_call_to(node.value, "Field") or self._is_call_to(
                node.value, "mapped_column"
            ):
                for keyword in node.value.keywords:
                    if keyword.arg == "primary_key" and isinstance(keyword.value, ast.Constant):
                        is_primary_key = bool(keyword.value.value)
                    elif keyword.arg == "foreign_key" and isinstance(keyword.value, ast.Constant):
                        is_foreign_key = True
                        foreign_table = str(keyword.value.value)
                    elif keyword.arg == "index" and isinstance(keyword.value, ast.Constant):
                        index = bool(keyword.value.value)
                    elif keyword.arg == "unique" and isinstance(keyword.value, ast.Constant):
                        is_unique = bool(keyword.value.value)
                    elif (
                        keyword.arg == "nullable"
                        and isinstance(keyword.value, ast.Constant)
                        and isinstance(keyword.value.value, bool)
                    ):
                        # An explicit nullable=True/False is what the database gets
                        # and overrides the annotation; nullable=None means
                        # "unspecified", so the annotation still decides.
                        is_nullable = keyword.value.value

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

        # A primary key is never NULL in the database. SQLModel's idiomatic
        # `id: int | None = Field(default=None, primary_key=True)` only means
        # "unset until the database assigns it", so drop the Optional and the
        # `None` default rather than render the key as nullable (#217). Keyless
        # sources (Pydantic/dataclass) describe objects, not tables: an inferred
        # `id: int | None = None` there really is optional, so keep it.
        if is_primary_key and model_kind in ("sqlmodel", "sqlalchemy"):
            is_nullable = False
            if default_value == "None":
                default_value = None

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
            # is_unique is reserved for non-PK uniqueness (see FieldInfo).
            is_unique=is_unique and not is_primary_key,
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
                ASTDatabaseParser._is_call_to(arg, "ForeignKey")  # also sa.ForeignKey
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
            is_field = self._is_call_to(node.value, "Field")
            if is_field or self._is_call_to(node.value, "mapped_column"):
                # Positional default: only SQLModel's Field(default, ...).
                # mapped_column()'s positional args are the column name, type
                # and ForeignKey, never a default (#221).
                if node.value.args and is_field:
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

    def _parse_relationship(self, node: ast.AnnAssign) -> _Rel | None:
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
        resolved = self._annotation_target(node.annotation)
        if resolved is not None:
            target, rel_type = resolved
        else:  # not a single-model annotation: keep the historical best effort
            type_str = self._unwrap_mapped(ast.unparse(node.annotation))
            rel_type = "many" if ("list[" in type_str or "List[" in type_str) else "one"
            target = self._clean_target(type_str)
        nullable = rel_type == "one" and self._is_optional_annotation(node.annotation)

        return (target, rel_type, field_name, nullable)

    def _parse_model_reference(self, node: ast.AnnAssign) -> _Rel | None:
        """Treat a field typed as another known model as a relationship.

        Used for Pydantic/dataclass models, which express relationships as plain
        typed attributes (e.g. ``user: User`` or ``items: list[Item]``) rather
        than via a Relationship()/relationship() call.
        """
        if not isinstance(node.target, ast.Name):
            return None

        resolved = self._annotation_target(node.annotation)
        if resolved is None:
            return None
        target, rel_type = resolved

        target_class = self._all_classes.get(target)
        if target_class is not None and self._classify_source(target_class) is not None:
            # `user: User | None` is an optional reference (#223).
            nullable = rel_type == "one" and self._is_optional_annotation(node.annotation)
            return (target, rel_type, node.target.id, nullable)
        return None

    #: Subscript wrappers whose (first) argument is the annotated type itself.
    _TRANSPARENT_WRAPPERS = frozenset({"Mapped", "Optional", "Annotated"})
    #: Containers that make a reference "many".
    _MANY_CONTAINERS = frozenset({"list", "List"})

    @classmethod
    def _annotation_target(cls, node: ast.expr, many: bool = False) -> Tuple[str, str] | None:
        """``(class name, "one" | "many")`` if an annotation names exactly one class.

        Walks the annotation AST through ``Mapped[...]``, ``Optional[...]``,
        ``Annotated[X, ...]``, ``Union[X, None]`` / ``X | None`` (``None`` on
        either side), one ``list[...]`` / ``List[...]`` level, string forward
        references, and ``typing.``-qualified forms (#229). Anything else, such
        as ``Union[User, int]`` or ``dict[str, User]``, returns None.
        """
        if isinstance(node, ast.Constant):
            if not isinstance(node.value, str):
                return None
            try:
                parsed = ast.parse(node.value, mode="eval").body
            except SyntaxError:
                return None
            return cls._annotation_target(parsed, many)
        if isinstance(node, ast.Name):
            return node.id, "many" if many else "one"
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            return cls._single_non_none(cls._union_operands(node), many)
        if isinstance(node, ast.Subscript):
            func = node.value
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
            else:
                return None
            args = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
            if name in cls._TRANSPARENT_WRAPPERS and args:
                return cls._annotation_target(args[0], many)
            if name == "Union":
                return cls._single_non_none(args, many)
            if name in cls._MANY_CONTAINERS and not many and len(args) == 1:
                return cls._annotation_target(args[0], True)
        return None

    @classmethod
    def _union_operands(cls, node: ast.expr) -> List[ast.expr]:
        """Flatten ``A | B | C`` into its operands."""
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            return [*cls._union_operands(node.left), *cls._union_operands(node.right)]
        return [node]

    @classmethod
    def _single_non_none(cls, options: List[ast.expr], many: bool) -> Tuple[str, str] | None:
        """Resolve a union that is exactly one type plus optional ``None``."""
        rest = [o for o in options if not (isinstance(o, ast.Constant) and o.value is None)]
        if len(rest) != 1:
            return None
        return cls._annotation_target(rest[0], many)

    @classmethod
    def _is_optional_annotation(cls, node: ast.expr) -> bool:
        """Whether an annotation admits ``None`` at its top level.

        Recognizes ``X | None`` (either side), ``Optional[X]``,
        ``Union[..., None]``, the same inside ``Mapped[...]`` or as the first
        argument of ``Annotated[...]``, and string
        (forward-reference) annotations. A name that merely contains
        "Optional" or "None" (``OptionalSettings``) is not optional.
        """
        if isinstance(node, ast.Constant):
            if node.value is None:
                return True
            if isinstance(node.value, str):
                try:
                    parsed = ast.parse(node.value, mode="eval").body
                except SyntaxError:
                    return False
                return cls._is_optional_annotation(parsed)
            return False
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            return cls._is_optional_annotation(node.left) or cls._is_optional_annotation(node.right)
        if isinstance(node, ast.Subscript):
            func = node.value
            name = (
                func.id
                if isinstance(func, ast.Name)
                else func.attr
                if isinstance(func, ast.Attribute)
                else None
            )
            if name == "Optional":
                return True
            if name == "Mapped":
                return cls._is_optional_annotation(node.slice)
            if name == "Annotated" and isinstance(node.slice, ast.Tuple) and node.slice.elts:
                return cls._is_optional_annotation(node.slice.elts[0])
            if name == "Union":
                args = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
                return any(cls._is_optional_annotation(arg) for arg in args)
        return False

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
    *,
    exclude_patterns: List[str] | None = None,
    infer_keys: bool = False,
    sources: List[str] | None = None,
    django_raw_types: bool = False,
    exclude_paths: List[str] | None = None,
    use_default_excludes: bool = True,
    include_patterns: List[str] | None = None,
    hint_unmatched_model_packages: bool = False,
    sql_dialect: str | None = None,
    base_classes: List[str] | None = None,
    strict: bool = False,
) -> Tuple[Dict[str, EntityInfo], Dict[str, EnumInfo]]:
    """
    Parse Python model frameworks (SQLModel, SQLAlchemy, Django, Pydantic, dataclass)
    and SQL DDL (`.sql` files via the SQL frontend) from ``path``.

    ``path`` may be a single file or a directory; ``sql_dialect`` selects the SQL
    dialect passed to sqlglot (e.g. ``"postgres"``), or ``None`` for generic mode.

    Args:
        path: Path to directory containing model files, or a single file. When
            a file is given it is treated as the sole include target (base is the
            parent directory).
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
        hint_unmatched_model_packages: Warn once on stderr about a ``models/``
            package that the include patterns skip. Ignored when ``path`` is a
            file. The CLI enables it only for the default include pattern.
        sql_dialect: Optional SQL dialect hint passed to ``SqlSchemaParser``
            (e.g. ``"postgres"``). ``None`` uses sqlglot's dialect-agnostic mode.
        base_classes: Extra base-class names to treat as Pydantic models, for
            bases defined outside the scanned files (``["Schema"]`` for
            django-ninja, or an internal shared ``BaseSchema``).
        strict: Raise :class:`ModelParseError` if any Python or ``.sql`` file
            fails to parse. Without it, such a file is reported on stderr and
            skipped, and the rest is still returned.

    Returns:
        Tuple of (entities, enums), both keyed by name. Python models win over
        SQL tables of the same name.

    Raises:
        SqlDependencyError: ``.sql`` files were found but the optional
            ``sqlglot`` dependency (``erdify[sql]``) is not installed.
        ModelParseError: ``strict`` is set and at least one file failed to
            parse. It lists the failures from both the Python and SQL scans.
    """
    # Normalize a file input: treat it as base=parent with that file as the sole include.
    if path.is_file():
        base = path.parent
        include = [path.name]
        hint = False
    else:
        base = path
        include = include_patterns if include_patterns is not None else ["models.py"]
        hint = hint_unmatched_model_packages

    parser = ASTDatabaseParser(
        base,
        exclude_patterns=exclude_patterns,
        infer_keys=infer_keys,
        sources=sources,
        django_raw_types=django_raw_types,
        exclude_paths=exclude_paths,
        use_default_excludes=use_default_excludes,
        include_patterns=include,
        hint_unmatched_model_packages=hint,
        base_classes=base_classes,
    )
    entities, enums = parser.parse_all_models()
    parse_errors = list(parser._parse_errors)

    from .sql_parser import SqlSchemaParser, discover_sql_files

    sql_files = discover_sql_files(base, include, exclude_paths or [], use_default_excludes)
    if sql_files:
        sql_parser = SqlSchemaParser(
            sql_files, dialect=sql_dialect, exclude_patterns=exclude_patterns
        )
        sql_entities, sql_enums = sql_parser.parse()
        parse_errors.extend(sql_parser._parse_errors)
        for name, entity in sql_entities.items():
            entities.setdefault(name, entity)
        for name, enum in sql_enums.items():
            enums.setdefault(name, enum)

    # Collect failures from both scans before raising, so one run reports them all.
    if strict and parse_errors:
        raise ModelParseError(parse_errors)

    return entities, enums


@dataclass(frozen=True)
class ScanReport:
    """How a discovery walk selected files — used to explain an empty result.

    Attributes:
        base: Directory the walk started from.
        include_patterns: Patterns that were in effect.
        candidate_files: ``.py``/``.sql`` files seen after directory pruning,
            i.e. the population ``include_patterns`` selected from.
        matched_files: Files the patterns selected, after ``exclude_paths``.
    """

    base: Path
    include_patterns: List[str]
    candidate_files: int
    matched_files: int


def scan_report(
    path: Path,
    exclude_paths: List[str] | None = None,
    use_default_excludes: bool = True,
    include_patterns: List[str] | None = None,
) -> ScanReport:
    """Re-run file discovery for ``path`` and report what it selected.

    Runs the same discovery as :func:`parse_models_directory` without parsing
    anything, so a caller that got no entities can tell "nothing matched the
    include patterns" apart from "files matched but held no recognized models".
    The arguments mirror the discovery-related parameters of
    :func:`parse_models_directory`.
    """
    if path.is_file():
        base = path.parent
        include = [path.name]
    else:
        base = path
        include = include_patterns if include_patterns is not None else ["models.py"]

    parser = ASTDatabaseParser(
        base,
        exclude_paths=exclude_paths,
        use_default_excludes=use_default_excludes,
        include_patterns=include,
    )
    python_files = parser._discover_model_files()

    from .sql_parser import discover_sql_files

    sql_files = discover_sql_files(base, include, exclude_paths or [], use_default_excludes)

    return ScanReport(
        base=base,
        include_patterns=list(include),
        candidate_files=parser._candidate_file_count,
        matched_files=len(python_files) + len(sql_files),
    )
