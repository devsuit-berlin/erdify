"""Report framework release series that are out but not in the CI test matrices.

Used by the scheduled ``upstream.yml`` workflow. It reads the Django and
SQLAlchemy series from ``.github/workflows/test.yml``, asks PyPI for the newest
final release of each framework, and exits with status 1, listing what is
missing, when a newer series is out. A new series must be added to the matrix
and to the "Supported framework versions" table in ``docs/installation.md``
together (see ``.github/copilot-instructions.md``).

Run: ``uv run --no-project --with pyyaml --with packaging python scripts/check_upstream_series.py``
"""

from __future__ import annotations

import json
import sys
import urllib.request
from collections.abc import Iterable
from pathlib import Path

import yaml
from packaging.version import InvalidVersion, Version

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "test.yml"


def matrix_series(workflow: dict) -> dict[str, set[str]]:
    """The ``major.minor`` series each framework is tested on in ``test.yml``."""
    jobs = workflow["jobs"]
    django = {str(v) for v in jobs["django"]["strategy"]["matrix"]["django"]}
    sqlalchemy = {
        str(leg["sqlalchemy"]) for leg in jobs["sqlalchemy"]["strategy"]["matrix"]["include"]
    }
    return {"django": django, "sqlalchemy": sqlalchemy}


def newest_series(versions: Iterable[str]) -> str | None:
    """``major.minor`` of the newest final release (pre-releases and dev builds ignored)."""
    finals = []
    for raw in versions:
        try:
            version = Version(raw)
        except InvalidVersion:
            continue
        if not (version.is_prerelease or version.is_devrelease):
            finals.append(version)
    if not finals:
        return None
    newest = max(finals)
    return f"{newest.major}.{newest.minor}"


def missing_series(tested: dict[str, set[str]], released: dict[str, list[str]]) -> list[str]:
    """One message per framework whose newest series is not tested."""
    messages = []
    for name, series in sorted(tested.items()):
        newest = newest_series(released.get(name, []))
        if newest is not None and newest not in series:
            messages.append(
                f"{name} {newest} is out but not in the CI matrix "
                f"(tested: {', '.join(sorted(series, key=Version))})"
            )
    return messages


def pypi_releases(name: str) -> list[str]:
    """All release versions of ``name`` on PyPI that have files."""
    url = f"https://pypi.org/pypi/{name}/json"
    request = urllib.request.Request(url, headers={"User-Agent": "erdify-ci-upstream-check"})
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - fixed https URL
        data = json.load(response)
    return [version for version, files in data["releases"].items() if files]


def main() -> int:
    tested = matrix_series(yaml.safe_load(WORKFLOW.read_text(encoding="utf-8")))
    released = {name: pypi_releases(name) for name in tested}
    for name in sorted(tested):
        print(
            f"{name}: newest series {newest_series(released[name])}, tested {sorted(tested[name])}"
        )
    messages = missing_series(tested, released)
    for message in messages:
        print(f"::error::{message}")
    return 1 if messages else 0


if __name__ == "__main__":
    sys.exit(main())
