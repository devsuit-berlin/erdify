"""Ensure test fixtures remain valid, importable Python modules.

erdify parses models purely via the stdlib ``ast`` module and never imports
the user's code. The fixtures therefore *look* like real SQLModel / SQLAlchemy
/ Pydantic / dataclass models but are only ever read as text by the parser.

This smoke test guards against fixtures silently rotting into code that no
longer imports (e.g. wrong API usage after a library upgrade), which would make
them poor stand-ins for the real models erdify targets. The ``malformed``
fixture is excluded on purpose - it contains syntax errors by design.
"""

import importlib.util
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# malformed: contains deliberate syntax errors to exercise the parser's error
# handling. django: Django models cannot be imported standalone (they require a
# configured settings module / app registry); erdify only ever reads them as
# text, and the django fixture is exercised end-to-end by test_django.py.
EXCLUDED = {"malformed", "django"}

FIXTURE_MODULES = sorted(
    path for path in FIXTURES_DIR.glob("*/models.py") if path.parent.name not in EXCLUDED
)


@pytest.mark.parametrize("models_path", FIXTURE_MODULES, ids=lambda p: p.parent.name)
def test_fixture_module_imports(models_path: Path) -> None:
    """Each non-malformed fixture must be importable, runnable Python."""
    module_name = f"_fixture_{models_path.parent.name}"
    spec = importlib.util.spec_from_file_location(module_name, models_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
