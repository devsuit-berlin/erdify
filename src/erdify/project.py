"""Resolve settings and parse a project the way the ``erdify`` command does (#360).

:func:`load_project` takes an input path and option overrides, resolves them
against the ``[tool.erdify]`` table of the nearest ``pyproject.toml`` exactly
like the CLI (an override beats the config, the config beats the default,
boolean flags merge by OR, ``output`` / ``inject`` from the config resolve
from the ``pyproject.toml`` folder) and parses the models. A tool built on
erdify reads the same model set ``erdify`` would draw for the project.
"""

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from .config import EntityInfo, EnumInfo
from .pyproject import ConfigError, load_config

#: Output formats, in the order ``--format`` lists them.
FORMAT_NAMES = ("plantuml", "mermaid", "json", "html")

_LIST_KEYS = ("sources", "exclude", "exclude_paths", "include", "base_classes")
_FLAG_KEYS = (
    "infer_keys",
    "django_raw_types",
    "no_enums",
    "no_relationships",
    "no_default_excludes",
    "allow_empty",
    "strict",
)


@dataclass(frozen=True)
class Settings:
    """Settings resolved from overrides, ``[tool.erdify]`` and the defaults.

    The attributes mirror the CLI options and ``[tool.erdify]`` keys
    (``format`` is ``formats``, always a list).

    Attributes:
        input: The input path (a directory or a file), as given.
        pyproject: The ``pyproject.toml`` whose ``[tool.erdify]`` table was
            read: the nearest one above ``input``. None when there is none.
        title: Diagram title.
        sources: Model kinds to draw (``MODEL_SOURCES``); None for all.
        sql_dialect: sqlglot dialect for ``.sql`` files; None for generic.
        include: Globs selecting the scanned files (default ``["models.py"]``).
        include_is_default: ``include`` was set neither by an override nor by
            the config.
        exclude: Entity name / table name globs to leave out.
        exclude_paths: File path globs to skip.
        base_classes: Extra Pydantic base-class names.
        infer_keys: Infer keys for Pydantic / dataclass models.
        django_raw_types: Show Django field class names.
        no_enums: Leave enums out of the diagram.
        no_relationships: Leave relationships out of the diagram.
        no_default_excludes: Scan virtualenvs and caches too.
        allow_empty: An input without entities is not an error.
        strict: A file that fails to parse is an error.
        output: Output path (a config path resolved from the ``pyproject.toml``
            folder); None for stdout.
        inject: Markdown file to embed the diagram in (resolved like
            ``output``); None when not injecting.
        formats: Output formats; the default is ``["mermaid"]`` when
            injecting, else ``["plantuml"]``. Unknown names are dropped with a
            warning on stderr.
    """

    input: Path
    pyproject: Path | None
    title: str
    sources: List[str] | None
    sql_dialect: str | None
    include: List[str]
    include_is_default: bool
    exclude: List[str]
    exclude_paths: List[str]
    base_classes: List[str]
    infer_keys: bool
    django_raw_types: bool
    no_enums: bool
    no_relationships: bool
    no_default_excludes: bool
    allow_empty: bool
    strict: bool
    output: Path | None
    inject: Path | None
    formats: List[str]


@dataclass(frozen=True)
class Project:
    """A parsed project: its resolved settings and the model set erdify draws.

    Attributes:
        settings: The resolved :class:`Settings`.
        entities: Parsed entities, keyed by name, after ``exclude``.
        enums: Parsed enums, keyed by name.
    """

    settings: Settings
    entities: Dict[str, EntityInfo]
    enums: Dict[str, EnumInfo]


def resolve_settings(path: Path, **overrides: Any) -> Settings:
    """Resolve the settings for ``path`` like the ``erdify`` command.

    Args:
        path: Input directory or file, as passed to ``erdify``.
        **overrides: Settings that win over ``[tool.erdify]``, named like its
            keys (``title``, ``include``, ``sql_dialect``, ``format``,
            ``infer_keys``, ...). ``None`` means "not given", as an omitted
            CLI option. A boolean flag only turns a setting on: ``True``
            enables it, ``False`` leaves the config's value (flags merge by
            OR, as on the command line). ``output`` / ``inject`` overrides
            are taken as given, not resolved from the ``pyproject.toml``.

    Returns:
        The resolved settings, naming the ``pyproject.toml`` they read.

    Raises:
        FileNotFoundError: ``path`` does not exist.
        ConfigError: ``[tool.erdify]`` has an invalid value, or an override
            names an unknown setting.
    """
    if not path.exists():
        raise FileNotFoundError(f"Input path does not exist: {path}")
    unknown = set(overrides) - _OVERRIDE_KEYS
    if unknown:
        raise ConfigError(f"unknown setting(s): {', '.join(sorted(unknown))}")
    config, base_dir = load_config(path)

    def pick(key: str, default: Any) -> Any:
        value = overrides.get(key)
        return value if value is not None else config.get(key, default)

    def flag(key: str) -> bool:
        return bool(overrides.get(key)) or bool(config.get(key, False))

    def config_path(key: str) -> Path | None:
        value = overrides.get(key)
        if value is not None:
            return Path(value)
        if key not in config:
            return None
        resolved = Path(config[key])
        if not resolved.is_absolute() and base_dir is not None:
            resolved = base_dir / resolved
        return resolved

    inject = config_path("inject")
    default_format = "mermaid" if inject is not None else "plantuml"
    formats = pick("format", [default_format])
    if isinstance(formats, str):
        formats = [formats]
    known = []
    for fmt in formats:
        if fmt in FORMAT_NAMES:
            known.append(fmt)
        else:
            print(f"Warning: unknown format '{fmt}', ignoring", file=sys.stderr)

    return Settings(
        input=path,
        pyproject=base_dir / "pyproject.toml" if base_dir is not None else None,
        title=pick("title", "Database ERD"),
        sources=pick("sources", None),
        sql_dialect=pick("sql_dialect", None),
        include=pick("include", ["models.py"]),
        include_is_default=overrides.get("include") is None and "include" not in config,
        exclude=pick("exclude", []),
        exclude_paths=pick("exclude_paths", []),
        base_classes=pick("base_classes", []),
        **{key: flag(key) for key in _FLAG_KEYS},
        output=config_path("output"),
        inject=inject,
        formats=known or [default_format],
    )


_OVERRIDE_KEYS = frozenset(
    {"title", "sql_dialect", "output", "inject", "format", *_LIST_KEYS, *_FLAG_KEYS}
)


def load_project(path: Path, **overrides: Any) -> Project:
    """Resolve the settings for ``path`` and parse its models, like ``erdify``.

    Returns the model set the ``erdify`` command would draw for the same
    input and options. Warnings (an unknown ``[tool.erdify]`` key, a file that
    fails to parse without ``strict``) go to stderr, as on the command line.

    Args:
        path: Input directory or file, as passed to ``erdify``.
        **overrides: As for :func:`resolve_settings`.

    Raises:
        FileNotFoundError: ``path`` does not exist.
        ConfigError: An invalid ``[tool.erdify]`` value or unknown override.
        SqlDependencyError: ``.sql`` files were found but ``erdify[sql]`` is
            not installed.
        ModelParseError: ``strict`` is on and a file failed to parse.
    """
    settings = resolve_settings(path, **overrides)
    entities, enums = parse_settings(settings)
    return Project(settings=settings, entities=entities, enums=enums)


def parse_settings(
    settings: Settings, *, hint_unmatched_model_packages: bool = False
) -> "tuple[Dict[str, EntityInfo], Dict[str, EnumInfo]]":
    """Parse the models ``settings`` select (internal; the CLI passes the hint)."""
    from .parser import parse_models_directory

    return parse_models_directory(
        settings.input,
        exclude_patterns=settings.exclude,
        infer_keys=settings.infer_keys,
        sources=settings.sources,
        django_raw_types=settings.django_raw_types,
        exclude_paths=settings.exclude_paths,
        use_default_excludes=not settings.no_default_excludes,
        include_patterns=settings.include,
        hint_unmatched_model_packages=hint_unmatched_model_packages,
        sql_dialect=settings.sql_dialect,
        base_classes=settings.base_classes,
        strict=settings.strict,
    )
