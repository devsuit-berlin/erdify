"""The series check run by the scheduled upstream workflow (scripts/check_upstream_series.py)."""

import importlib.util
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "check_upstream_series", ROOT / "scripts" / "check_upstream_series.py"
)
assert _spec is not None and _spec.loader is not None
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)


def test_newest_series_ignores_pre_releases_and_bad_versions() -> None:
    assert check.newest_series(["5.2.19", "6.1.3", "6.2a1", "6.2rc1", "7.0.dev0", "junk"]) == "6.1"
    assert check.newest_series(["6.2rc1"]) is None
    assert check.newest_series([]) is None


def test_missing_series_reports_only_untested_newest_series() -> None:
    tested = {"django": {"5.2", "6.0", "6.1"}, "sqlalchemy": {"2.0", "2.1"}}
    assert check.missing_series(tested, {"django": ["6.1.3"], "sqlalchemy": ["2.1.8"]}) == []
    messages = check.missing_series(tested, {"django": ["6.2.0"], "sqlalchemy": ["2.1.8"]})
    assert messages == ["django 6.2 is out but not in the CI matrix (tested: 5.2, 6.0, 6.1)"]


def test_matrix_series_reads_the_real_workflow() -> None:
    """The workflow layout the script relies on: a change to test.yml must keep it working."""
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "test.yml").read_text())
    series = check.matrix_series(workflow)
    assert {"5.2", "6.0", "6.1"} <= series["django"]
    assert {"2.0", "2.1"} <= series["sqlalchemy"]
