"""Resolve settings and parse a project the way the ``erdify`` command does (#360).

:func:`load_project` takes an input path and option overrides, resolves them
against the ``[tool.erdify]`` table of the nearest ``pyproject.toml`` exactly
like the CLI (an override beats the config, the config beats the default;
``output`` / ``inject`` from the config resolve from the ``pyproject.toml``
folder) and parses the models. A tool built on erdify reads the same model
set ``erdify`` would draw for the project.
"""

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence, Tuple

from .config import EntityInfo, EnumInfo
from .pyproject import ConfigError, load_config

#: Output formats, in the order ``--format`` lists them.
FORMAT_NAMES = ("plantuml", "mermaid", "json", "html")


@dataclass(frozen=True)
class Settings:
    """Settings resolved from overrides, ``[tool.erdify]`` and the defaults.

    The attributes mirror the CLI options and ``[tool.erdify]`` keys
    (``format`` is ``formats``, always a tuple). Build one with
    :func:`resolve_settings`; constructing it yourself is not supported, and
    new attributes may be added in a minor release.

    Attributes:
        input: The input path (a directory or a file), as given.
        pyproject: The nearest ``pyproject.toml`` above ``input``, whose
            ``[tool.erdify]`` table the settings come from; None when there
            is none. A file that can't be read is reported on stderr and
            gives no settings, but is still named here.
        title: Diagram title.
        sources: Model kinds to draw (``MODEL_SOURCES``); None for all.
        sql_dialect: sqlglot dialect for ``.sql`` files; None for generic.
        include: Globs selecting the scanned files (default ``("models.py",)``).
            Not used when ``input`` is a file: then only that file is read.
        exclude: Entity name / table name / ``schema.table`` globs to leave out.
        exclude_paths: File path globs to skip.
        base_classes: Extra Pydantic base-class names.
        infer_keys: Infer keys for Pydantic / dataclass models.
        django_raw_types: Show Django field class names.
        no_enums: Leave enums out of the diagram.
        no_relationships: Leave relationships out of the diagram.
        no_default_excludes: Scan virtualenvs and caches too.
        allow_empty: An input without entities is not an error (CLI).
        strict: A file that fails to parse is an error.
        output: Output path (a config path resolved from the ``pyproject.toml``
            folder); None for stdout.
        inject: Markdown file to embed the diagram in (resolved like
            ``output``); None when not injecting.
        formats: Output formats; the default is ``("mermaid",)`` when
            injecting, else ``("plantuml",)``. Unknown names are dropped with
            a warning on stderr.
    """

    input: Path
    pyproject: Path | None
    title: str
    sources: Tuple[str, ...] | None
    sql_dialect: str | None
    include: Tuple[str, ...]
    exclude: Tuple[str, ...]
    exclude_paths: Tuple[str, ...]
    base_classes: Tuple[str, ...]
    infer_keys: bool
    django_raw_types: bool
    no_enums: bool
    no_relationships: bool
    no_default_excludes: bool
    allow_empty: bool
    strict: bool
    output: Path | None
    inject: Path | None
    formats: Tuple[str, ...]


@dataclass(frozen=True)
class Project:
    """A parsed project: its resolved settings and the model set erdify draws.

    Built by :func:`load_project`; constructing it yourself is not
    supported, and new attributes may be added in a minor release.

    Attributes:
        settings: The resolved :class:`Settings`.
        entities: Parsed entities, keyed by name, after ``exclude``.
        enums: Parsed enums, keyed by name.
    """

    settings: Settings
    entities: Dict[str, EntityInfo]
    enums: Dict[str, EnumInfo]


def resolve_settings(
    path: "str | os.PathLike[str]",
    *,
    title: str | None = None,
    output: Path | str | None = None,
    inject: Path | str | None = None,
    format: str | Sequence[str] | None = None,
    sources: Sequence[str] | None = None,
    exclude: Sequence[str] | None = None,
    exclude_paths: Sequence[str] | None = None,
    include: Sequence[str] | None = None,
    base_classes: Sequence[str] | None = None,
    sql_dialect: str | None = None,
    infer_keys: bool | None = None,
    django_raw_types: bool | None = None,
    no_enums: bool | None = None,
    no_relationships: bool | None = None,
    no_default_excludes: bool | None = None,
    allow_empty: bool | None = None,
    strict: bool | None = None,
) -> Settings:
    """Resolve the settings for ``path`` like the ``erdify`` command.

    Every keyword is named like its ``[tool.erdify]`` key and wins over it;
    ``None`` (the default) means "not given": the config's value, else the
    built-in default, applies. A boolean ``False`` turns a setting off even
    when the config turns it on. ``output`` / ``inject`` are taken as given,
    not resolved from the ``pyproject.toml`` folder (the CLI passes paths
    relative to the working directory).

    Args:
        path: Input directory or file, as passed to ``erdify`` (a ``str`` or
            path-like object).

    Returns:
        The resolved settings, naming the ``pyproject.toml`` they come from.

    Raises:
        FileNotFoundError: ``path`` does not exist.
        ConfigError: ``[tool.erdify]`` or an argument has a value of the
            wrong type (an argument: a string where a list of strings
            belongs, a flag that is not a bool; in ``[tool.erdify]`` one
            string for a list is read as a list of it).
    """
    overrides = {
        "title": title,
        "output": output,
        "inject": inject,
        "format": format,
        "sources": sources,
        "exclude": exclude,
        "exclude_paths": exclude_paths,
        "include": include,
        "base_classes": base_classes,
        "sql_dialect": sql_dialect,
        "infer_keys": infer_keys,
        "django_raw_types": django_raw_types,
        "no_enums": no_enums,
        "no_relationships": no_relationships,
        "no_default_excludes": no_default_excludes,
        "allow_empty": allow_empty,
        "strict": strict,
    }
    return _resolve(path, overrides)[0]


_FLAG_KEYS = (
    "infer_keys",
    "django_raw_types",
    "no_enums",
    "no_relationships",
    "no_default_excludes",
    "allow_empty",
    "strict",
)


def _resolve(path: "str | os.PathLike[str]", overrides: Mapping[str, Any]) -> Tuple[Settings, bool]:
    """The settings, and whether ``include`` was left at its default (the CLI's hint)."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Input path does not exist: {path}")
    for key in ("sources", "exclude", "exclude_paths", "include", "base_classes"):
        _check_strings(key, overrides.get(key), "argument")
    for key in _FLAG_KEYS:
        value = overrides.get(key)
        if value is not None and not isinstance(value, bool):
            raise ConfigError(f"argument '{key}' must be a bool or None, got {value!r}")
    config, base_dir = load_config(path)

    def pick(key: str, default: Any) -> Any:
        value = overrides.get(key)
        return value if value is not None else config.get(key, default)

    def flag(key: str) -> bool:
        value = overrides.get(key)
        return bool(value) if value is not None else bool(config.get(key, False))

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
    _check_strings("format", formats, "argument")
    known = []
    for fmt in formats:
        if fmt in FORMAT_NAMES:
            known.append(fmt)
        else:
            print(f"Warning: unknown format '{fmt}', ignoring", file=sys.stderr)

    sources = pick("sources", None)
    settings = Settings(
        input=path,
        pyproject=base_dir / "pyproject.toml" if base_dir is not None else None,
        title=pick("title", "Database ERD"),
        sources=tuple(sources) if sources is not None else None,
        sql_dialect=pick("sql_dialect", None),
        include=tuple(pick("include", ["models.py"])),
        exclude=tuple(pick("exclude", [])),
        exclude_paths=tuple(pick("exclude_paths", [])),
        base_classes=tuple(pick("base_classes", [])),
        infer_keys=flag("infer_keys"),
        django_raw_types=flag("django_raw_types"),
        no_enums=flag("no_enums"),
        no_relationships=flag("no_relationships"),
        no_default_excludes=flag("no_default_excludes"),
        allow_empty=flag("allow_empty"),
        strict=flag("strict"),
        output=config_path("output"),
        inject=inject,
        formats=tuple(known or [default_format]),
    )
    include_is_default = overrides.get("include") is None and "include" not in config
    return settings, include_is_default


def _check_strings(key: str, value: object, what: str) -> None:
    """Raise :class:`ConfigError` unless ``value`` is None or a list / tuple of strings."""
    if value is None:
        return
    if not isinstance(value, (list, tuple)) or not all(isinstance(i, str) for i in value):
        raise ConfigError(f"{what} '{key}' must be a list of strings, got {value!r}")


def load_project(
    path: "str | os.PathLike[str]",
    *,
    title: str | None = None,
    output: Path | str | None = None,
    inject: Path | str | None = None,
    format: str | Sequence[str] | None = None,
    sources: Sequence[str] | None = None,
    exclude: Sequence[str] | None = None,
    exclude_paths: Sequence[str] | None = None,
    include: Sequence[str] | None = None,
    base_classes: Sequence[str] | None = None,
    sql_dialect: str | None = None,
    infer_keys: bool | None = None,
    django_raw_types: bool | None = None,
    no_enums: bool | None = None,
    no_relationships: bool | None = None,
    no_default_excludes: bool | None = None,
    allow_empty: bool | None = None,
    strict: bool | None = None,
) -> Project:
    """Resolve the settings for ``path`` and parse its models, like ``erdify``.

    Returns the model set the ``erdify`` command would draw for the same
    input and options. The keywords are those of :func:`resolve_settings`.
    Warnings (an unknown ``[tool.erdify]`` key or format, a file that fails
    to parse without ``strict``) go to stderr, as on the command line; the
    CLI's hint about a skipped ``models/`` package does not.

    Args:
        path: Input directory or file, as passed to ``erdify``.

    Raises:
        FileNotFoundError: ``path`` does not exist.
        ConfigError: An invalid ``[tool.erdify]`` value or override.
        SqlDependencyError: ``.sql`` files were found but ``erdify[sql]`` is
            not installed.
        ModelParseError: ``strict`` is on and a file failed to parse.
    """
    settings = resolve_settings(
        path,
        title=title,
        output=output,
        inject=inject,
        format=format,
        sources=sources,
        exclude=exclude,
        exclude_paths=exclude_paths,
        include=include,
        base_classes=base_classes,
        sql_dialect=sql_dialect,
        infer_keys=infer_keys,
        django_raw_types=django_raw_types,
        no_enums=no_enums,
        no_relationships=no_relationships,
        no_default_excludes=no_default_excludes,
        allow_empty=allow_empty,
        strict=strict,
    )
    entities, enums = parse_settings(settings)
    return Project(settings=settings, entities=entities, enums=enums)


def parse_settings(
    settings: Settings, *, hint_unmatched_model_packages: bool = False
) -> Tuple[Dict[str, EntityInfo], Dict[str, EnumInfo]]:
    """Parse the models ``settings`` select (internal; the CLI passes the hint)."""
    from .parser import parse_models_directory

    return parse_models_directory(
        settings.input,
        exclude_patterns=list(settings.exclude),
        infer_keys=settings.infer_keys,
        sources=list(settings.sources) if settings.sources is not None else None,
        django_raw_types=settings.django_raw_types,
        exclude_paths=list(settings.exclude_paths),
        use_default_excludes=not settings.no_default_excludes,
        include_patterns=list(settings.include),
        hint_unmatched_model_packages=hint_unmatched_model_packages,
        sql_dialect=settings.sql_dialect,
        base_classes=list(settings.base_classes),
        strict=settings.strict,
    )
