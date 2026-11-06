"""Find the model files to scan: include globs, exclude paths, default excludes."""

import os
import re
import sys
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path
from typing import List

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


def is_path_excluded(
    model_file: Path, base: Path, exclude_paths: List[str], use_default_excludes: bool
) -> bool:
    """Decide whether a discovered model file should be skipped before parsing.

    Skips files under a default non-project directory (venv/site-packages/
    caches, unless disabled) or matching an ``exclude_paths`` glob against the
    path relative to the input or any single path segment.
    """
    try:
        rel = model_file.relative_to(base).as_posix()
    except ValueError:
        rel = model_file.as_posix()
    segments = rel.split("/")[:-1]  # directory segments only (drop the filename)

    if use_default_excludes and any(seg in DEFAULT_EXCLUDE_DIRS for seg in segments):
        return True

    for pattern in exclude_paths:
        if fnmatchcase(rel, pattern) or any(fnmatchcase(seg, pattern) for seg in segments):
            return True

    return False


@dataclass
class Discovery:
    """The result of one discovery walk.

    Attributes:
        files: Selected ``.py`` model files, sorted.
        candidate_count: ``.py`` / ``.sql`` files seen after directory pruning
            (the population ``--include`` selects from).
        unmatched_model_packages: ``models/`` packages the include patterns skip.
    """

    files: List[Path] = field(default_factory=list)
    candidate_count: int = 0
    unmatched_model_packages: List[Path] = field(default_factory=list)


def discover_model_files(
    base: Path,
    include_patterns: List[str],
    exclude_paths: List[str],
    use_default_excludes: bool,
    hint_unmatched_model_packages: bool,
) -> Discovery:
    """Find model files, pruning excluded directories during the walk.

    Default-excluded dirs (venv/site-packages/caches) are removed from the
    traversal *before* descending, so large trees like ``.venv`` are never
    scandir'd. A file is selected when it matches ``include_patterns``
    (default ``["models.py"]``); ``exclude_paths`` then filters via
    :func:`is_path_excluded`. Results are sorted for deterministic output.
    """
    found: List[Path] = []
    model_packages: List[Path] = []
    candidate_count = 0
    for dirpath, dirnames, filenames in os.walk(base):
        if use_default_excludes:
            # In-place prune so os.walk does not descend into excluded dirs.
            dirnames[:] = [d for d in dirnames if d not in DEFAULT_EXCLUDE_DIRS]
        dpath = Path(dirpath)
        if (
            hint_unmatched_model_packages
            and dpath.name == "models"
            and any(f.endswith(".py") for f in filenames)
        ):
            model_packages.append(dpath)
        for filename in filenames:
            if filename.endswith((".py", ".sql")):
                candidate_count += 1
            if not filename.endswith(".py"):
                continue
            candidate = dpath / filename
            try:
                rel = candidate.relative_to(base).as_posix()
            except ValueError:
                rel = candidate.as_posix()
            if not _match_include(rel, filename, include_patterns):
                continue
            if not is_path_excluded(candidate, base, exclude_paths, use_default_excludes):
                found.append(candidate)
    # Only hint about packages whose files the current include patterns did
    # not already pick up; otherwise the "was not scanned" message is false.
    selected_dirs = {p.parent for p in found}
    unmatched = [p for p in model_packages if p not in selected_dirs]
    if unmatched:
        example = sorted(unmatched)[0]
        try:
            example_str = example.relative_to(base).as_posix()
        except ValueError:
            example_str = example.as_posix()
        print(
            f"Hint: found a models/ package ({example_str}) that was not scanned "
            f"(the default only matches models.py). Use "
            f"--include '**/models/*.py' to include it.",
            file=sys.stderr,
        )
    return Discovery(sorted(found), candidate_count, unmatched)
