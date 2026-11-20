"""Load erdify settings from a ``[tool.erdify]`` table in ``pyproject.toml``."""

import sys
import tomllib
from pathlib import Path
from typing import Any, Dict, Tuple

#: Recognized ``[tool.erdify]`` keys (mirror the CLI options).
CONFIG_KEYS = frozenset(
    {
        "title",
        "output",
        "inject",
        "format",
        "sources",
        "exclude",
        "exclude_paths",
        "include",
        "base_classes",
        "infer_keys",
        "django_raw_types",
        "no_enums",
        "no_relationships",
        "no_default_excludes",
        "allow_empty",
        "strict",
        "sql_dialect",
    }
)


class ConfigError(ValueError):
    """An invalid erdify setting: a ``[tool.erdify]`` value, or a
    :func:`erdify.load_project` / :func:`erdify.resolve_settings` argument, of
    the wrong type."""


def load_config(input_path: Path) -> Tuple[Dict[str, Any], Path | None]:
    """Find the nearest ``pyproject.toml`` and return its ``[tool.erdify]`` table.

    Walks up from ``input_path`` (a directory or file) to the filesystem root and
    reads the first ``pyproject.toml`` found. Returns ``(table, base_dir)`` where
    ``base_dir`` is that file's directory (used to resolve relative paths), or
    ``({}, None)`` if no ``pyproject.toml`` exists. Unknown keys are dropped with
    a warning.

    Raises:
        ConfigError: A key has a value of the wrong type.
    """
    start = input_path.resolve()
    if start.is_file():
        start = start.parent

    for directory in [start, *start.parents]:
        candidate = directory / "pyproject.toml"
        if not candidate.is_file():
            continue
        try:
            with open(candidate, "rb") as f:
                data = tomllib.load(f)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            print(f"Warning: could not read {candidate}: {exc}", file=sys.stderr)
            return {}, directory
        table = data.get("tool", {}).get("erdify", {}) or {}
        return _validate(table, candidate), directory

    return {}, None


def _validate(table: Dict[str, Any], source: Path) -> Dict[str, Any]:
    """Drop unknown ``[tool.erdify]`` keys, warning about each."""
    clean: Dict[str, Any] = {}
    for key, value in table.items():
        if key in CONFIG_KEYS:
            clean[key] = value
        else:
            print(f"Warning: unknown [tool.erdify] key '{key}' in {source}", file=sys.stderr)

    for str_key in ("title", "output", "inject", "sql_dialect"):
        if str_key in clean and not isinstance(clean[str_key], str):
            raise ConfigError(f"[tool.erdify] '{str_key}' must be a string in {source}")
    # A list setting given as one string means a list of that one string;
    # anything else must be a list of strings.
    for list_key in ("sources", "exclude", "exclude_paths", "include", "base_classes", "format"):
        value = clean.get(list_key)
        if isinstance(value, str):
            clean[list_key] = [value]
        elif value is not None and not (
            isinstance(value, list) and all(isinstance(item, str) for item in value)
        ):
            raise ConfigError(f"[tool.erdify] '{list_key}' must be a list of strings in {source}")

    return clean
