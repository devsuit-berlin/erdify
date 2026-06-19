"""SQL DDL frontend for erdify (optional, requires the `sql` extra: sqlglot)."""

import os
from fnmatch import fnmatchcase
from pathlib import Path

from .parser import DEFAULT_EXCLUDE_DIRS, _match_include


def discover_sql_files(
    base: Path,
    include_patterns: list[str],
    exclude_paths: list[str],
    use_default_excludes: bool,
) -> list[Path]:
    """Find .sql files under `base` matching `include_patterns`.

    Mirrors the Python scan: prunes DEFAULT_EXCLUDE_DIRS during the walk and
    skips files matching `exclude_paths` (path relative to base, or any segment).
    """
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(base):
        if use_default_excludes:
            dirnames[:] = [d for d in dirnames if d not in DEFAULT_EXCLUDE_DIRS]
        dpath = Path(dirpath)
        for filename in filenames:
            if not filename.endswith(".sql"):
                continue
            candidate = dpath / filename
            try:
                rel = candidate.relative_to(base).as_posix()
            except ValueError:
                rel = candidate.as_posix()
            if not _match_include(rel, filename, include_patterns):
                continue
            segments = rel.split("/")[:-1]
            if use_default_excludes and any(s in DEFAULT_EXCLUDE_DIRS for s in segments):
                continue
            if any(
                fnmatchcase(rel, p) or any(fnmatchcase(s, p) for s in segments)
                for p in exclude_paths
            ):
                continue
            found.append(candidate)
    return sorted(found)
