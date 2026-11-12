"""The parser entry points: :class:`ASTDatabaseParser` and :func:`parse_models_directory`."""

import ast
import copy
import sys
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Tuple

from ..config import EntityInfo, EnumInfo, is_structural_link_table
from .aliases import AliasResolver
from .common import is_enum_class
from .dialects import DIALECTS, ParseContext
from .discovery import discover_model_files
from .inheritance import ClassIndex


class ModelParseError(Exception):
    """Raised in strict mode when one or more input files could not be parsed.

    Attributes:
        errors: ``(file, message)`` for every failure, in scan order: one per
            file, or one per statement of a ``.sql`` file.
    """

    def __init__(self, errors: List[Tuple[Path, str]]):
        self.errors = errors
        paths = list(dict.fromkeys(str(path) for path, _ in errors))
        super().__init__(
            f"{len(paths)} file(s) could not be parsed (strict mode): {', '.join(paths)}"
        )


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
        self._file_trees: Dict[Path, ast.Module] = {}
        #: The file each class definition (by ``id`` of its node) was read from.
        self._class_files: Dict[int, Path] = {}
        #: Names given to the definitions a namesake extends -> their own name (#300).
        self._shadowed: Dict[str, str] = {}
        #: id() of such a definition -> the name it is kept under.
        self._renamed: Dict[int, str] = {}
        #: Classes and dialects (with their caches); renewed for each parse run.
        self._ctx = self._new_context()

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
        definitions: List[Tuple[ast.ClassDef, Path]] = []
        for model_file in model_files:
            try:
                with open(model_file, encoding="utf-8") as f:  # PEP 3120 default
                    content = f.read()
                tree = ast.parse(content)
                self._file_trees[model_file] = tree

                # Collect all class definitions
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef):
                        definitions.append((node, model_file))
            except Exception as e:
                print(f"Error parsing {model_file}: {e}", file=sys.stderr)
                self._parse_errors.append((model_file, str(e)))

        if self.strict and self._parse_errors:
            raise ModelParseError(self._parse_errors)
        self._collect_classes(definitions)

        # Second pass: process enum and model classes. Dialects (and their
        # caches) are fresh for each run.
        self._ctx = self._new_context()
        for class_node in self._all_classes.values():
            if class_node.name in self._shadowed:
                continue
            if is_enum_class(class_node, self._all_classes):
                self._parse_enum_class(class_node)
                continue
            source = self._classify_source(class_node)
            if source is not None and (self.sources is None or source in self.sources):
                reason = self._ctx.dialect(source).skip_reason(class_node)
                if reason is not None:
                    print(reason, file=sys.stderr)
                    continue
                self._parse_table_class(class_node, source)

        # Entities that are not classes, e.g. SQLAlchemy Core tables (#34, #305).
        for dialect in self._ctx.all_dialects():
            if self.sources is not None and dialect.kind not in self.sources:
                continue
            for entity in dialect.extra_entities(self._file_trees.values()):
                if entity.name not in self._entities:
                    self._entities[entity.name] = entity

        # Cross-entity adjustments, once every entity is built, Core tables
        # included (e.g. renamed columns that foreign keys elsewhere point at,
        # #275, #292).
        for dialect in self._ctx.all_dialects():
            dialect.finalize(self._entities)

        # Third pass: apply exclude patterns
        self._apply_exclude_patterns()

        return self._entities, self._enums

    def _collect_classes(self, definitions: List[Tuple[ast.ClassDef, Path]]) -> None:
        """Index every class by name; a later definition replaces an earlier one.

        ``class Item(Item)`` extends another definition of ``Item`` (#300): a
        class cannot extend itself. Its base is the latest ``Item`` before it
        in the same file or, in another file, the ``Item`` its ``from ...
        import Item`` names. That base is kept under a name of its own,
        ``Item@<line>``, which a copy of the extending class names as its base
        instead; it is not drawn, as the extending definition replaces it. A
        base that is a table model of its own (a Django model, a mapped
        SQLAlchemy class, a SQLModel table) would need drawing as a separate
        table, so it is not linked: the classes are indexed as before.
        """
        links: Dict[int, ast.ClassDef] = {}  # id() of an extending class -> its base
        for index, (node, model_file) in enumerate(definitions):
            if not _extends_namesake(node):
                continue
            base = next(
                (
                    earlier
                    for earlier, earlier_file in reversed(definitions[:index])
                    if earlier.name == node.name and earlier_file == model_file
                ),
                None,
            )
            if base is None:
                base = self._imported_namesake(node, model_file)
            if base is not None:
                links[id(node)] = base
        while True:
            self._index_classes(definitions, links)
            if not links:
                return
            ctx = self._new_context()
            tables = [
                extending
                for extending, base in links.items()
                for kind in [ctx.classify(self._all_classes[self._renamed[id(base)]])]
                if kind is not None and not ctx.dialect(kind).keyless
            ]
            if not tables:
                return
            for extending in tables:
                del links[extending]

    def _index_classes(
        self, definitions: List[Tuple[ast.ClassDef, Path]], links: Mapping[int, ast.ClassDef]
    ) -> None:
        """Fill the class index from ``definitions``, applying the namesake ``links``."""
        self._all_classes = {}
        self._class_files = {}
        self._shadowed = {}
        self._renamed = {}
        files = {id(node): model_file for node, model_file in definitions}
        bases = {id(base) for base in links.values()}
        for node, model_file in definitions:
            self._class_files[id(node)] = model_file
        for node, model_file in definitions:
            if id(node) in bases:
                continue
            if id(node) in links:
                node = self._extend(node, links, files)
                self._class_files[id(node)] = model_file
            self._all_classes[node.name] = node
        # Framework base classes the scanned models build on but whose source
        # isn't scanned (e.g. Django's AbstractUser, #277). They have no file.
        defined = set(self._all_classes)
        for dialect_class in DIALECTS:
            builtins = dialect_class.builtin_classes(self._file_trees.values(), defined)
            for name, builtin in builtins.items():
                self._all_classes.setdefault(name, builtin)

    def _extend(
        self, node: ast.ClassDef, links: Mapping[int, ast.ClassDef], files: Mapping[int, Path]
    ) -> ast.ClassDef:
        """A copy of ``node`` whose base of its own name is its linked base, renamed.

        The base is kept under a new name; one that extends a namesake itself
        is linked the same way first.
        """
        base = links[id(node)]
        name = self._renamed.get(id(base))
        if name is None:
            name = f"{node.name}@{base.lineno}"
            while name in self._shadowed:
                name += "'"
            self._renamed[id(base)] = name
            self._shadowed[name] = node.name
            renamed = copy.copy(self._extend(base, links, files) if id(base) in links else base)
            renamed.name = name
            self._all_classes[name] = renamed
            self._class_files[id(renamed)] = files[id(base)]
        extending = copy.copy(node)
        extending.bases = [
            ast.copy_location(ast.Name(id=name, ctx=ast.Load()), b)
            if isinstance(b, ast.Name) and b.id == node.name
            else b
            for b in node.bases
        ]
        return extending

    def _imported_namesake(self, node: ast.ClassDef, model_file: Path) -> ast.ClassDef | None:
        """The class ``from <module> import <name>`` binds, when exactly one scanned file is it.

        That is the module's last top-level definition of the name; several
        files matching the module path leave it unresolved.
        """
        imported = self._import_source(model_file, node.name)
        if imported is None:
            return None
        found: List[ast.ClassDef] = []
        for other_file, tree in self._file_trees.items():
            if other_file == model_file or not _is_module_file(other_file, model_file, imported):
                continue
            top = [
                stmt
                for stmt in tree.body
                if isinstance(stmt, ast.ClassDef) and stmt.name == node.name
            ]
            if top:
                found.append(top[-1])
        return found[0] if len(found) == 1 else None

    def _import_source(self, model_file: Path, name: str) -> Tuple[int, str] | None:
        """``(level, module)`` of the ``from <module> import <name>`` in a file, if any."""
        tree = self._file_trees.get(model_file)
        if tree is None:
            return None
        for stmt in tree.body:
            if isinstance(stmt, ast.ImportFrom) and any(
                alias.name == name and alias.asname in (None, name) for alias in stmt.names
            ):
                return stmt.level, stmt.module or ""
        return None

    def _discover_model_files(self) -> List[Path]:
        """Find model files (see :func:`discover_model_files`) and record the walk."""
        found = discover_model_files(
            self.database_path,
            self.include_patterns,
            self.exclude_paths,
            self.use_default_excludes,
            self.hint_unmatched_model_packages,
        )
        self._candidate_file_count = found.candidate_count
        self._unmatched_model_packages = found.unmatched_model_packages
        return found.files

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
            entity.inverse_relationships = {
                attr: inverse
                for attr, inverse in entity.inverse_relationships.items()
                if attr in kept
            }

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

    def _new_context(self) -> ParseContext:
        """A parse context over the collected classes, with fresh dialects."""
        return ParseContext(
            classes=ClassIndex(self._all_classes),
            infer_keys=self.infer_keys,
            django_raw_types=self.django_raw_types,
            base_classes=self.base_classes,
            aliases_for=self._alias_lookup(),
            file_of=lambda class_node: self._class_files.get(id(class_node)),
            trees=list(self._file_trees.values()),
            tree_of=self._tree_of,
        )

    def _tree_of(self, class_node: ast.ClassDef) -> ast.Module | None:
        """The syntax tree of the file ``class_node`` is defined in, if scanned."""
        model_file = self._class_files.get(id(class_node))
        return self._file_trees.get(model_file) if model_file is not None else None

    def _alias_lookup(self) -> "Callable[[ast.ClassDef], Mapping[str, ast.expr]]":
        """Class -> the column type aliases visible where it is defined (#249, #250)."""
        resolver = AliasResolver(self._file_trees, self._all_classes)
        class_files = self._class_files

        def aliases_for(class_node: ast.ClassDef) -> Mapping[str, ast.expr]:
            return resolver.aliases_for(class_files.get(id(class_node)), class_node.lineno)

        return aliases_for

    def _classify_source(self, class_node: ast.ClassDef) -> str | None:
        """Classify which model framework a class belongs to (:meth:`ParseContext.classify`).

        Returns one of ``MODEL_SOURCES``, or None if the class is not a
        drawable entity.
        """
        return self._ctx.classify(class_node)

    def _parse_table_class(self, class_node: ast.ClassDef, source: str) -> None:
        """Parse a table class and all its inherited fields."""
        dialect = self._ctx.dialect(source)
        table_name = dialect.table_name(class_node) or dialect.default_table_name(class_node)

        # Get base classes
        base_classes: List[str] = []
        for base in class_node.bases:
            if isinstance(base, ast.Name):
                base_classes.append(self._shadowed.get(base.id, base.id))

        entity = EntityInfo(
            name=class_node.name,
            table_name=table_name,
            base_classes=base_classes,
            source=source,
        )

        # Collect fields from this class and all base classes (recursively)
        fields_dict, relationships_dict = dialect.collect(class_node)

        entity.fields = list(fields_dict.values())
        rels = list(relationships_dict.values())
        entity.relationships = [(r.target, r.kind, r.attr) for r in rels]
        entity.nullable_relationships = [r.attr for r in rels if r.nullable]
        entity.inverse_relationships = {r.attr: r.inverse for r in rels if r.inverse}

        dialect.finish(entity, class_node)

        # Detect join tables structurally: an entity whose composite primary
        # key is made up entirely of foreign keys (with no payload columns) is
        # an association table regardless of its class name (#35, #118).
        entity.is_link_table = is_structural_link_table(entity.fields)

        self._entities[class_node.name] = entity


def _is_module_file(path: Path, importer: Path, source: Tuple[int, str]) -> bool:
    """Whether ``path`` is the module ``source`` (``(level, module)``) names from ``importer``."""
    level, module = source
    parts = [part for part in module.split(".") if part]
    stem = path.with_suffix("")
    own = list(stem.parent.parts) if path.name == "__init__.py" else list(stem.parts)
    if level == 0:
        return bool(parts) and own[-len(parts) :] == parts
    package = importer.parent
    for _ in range(level - 1):
        package = package.parent
    return own == list(package.joinpath(*parts).parts)


def _extends_namesake(node: ast.ClassDef) -> bool:
    """Whether a class names a base of its own name (``class Item(Item)``)."""
    return any(isinstance(base, ast.Name) and base.id == node.name for base in node.bases)


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

    from ..sql_parser import SqlSchemaParser, discover_sql_files

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

    from ..sql_parser import discover_sql_files

    sql_files = discover_sql_files(base, include, exclude_paths or [], use_default_excludes)

    return ScanReport(
        base=base,
        include_patterns=list(include),
        candidate_files=parser._candidate_file_count,
        matched_files=len(python_files) + len(sql_files),
    )
