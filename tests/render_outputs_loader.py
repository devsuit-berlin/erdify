"""Load ``scripts/render_outputs.py`` (not a package) once, for the tests that use its sources."""

import importlib.util
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def render_outputs() -> Any:
    """The ``render_outputs`` script as a module, loaded once per test session."""
    if "render_outputs" in sys.modules:
        return sys.modules["render_outputs"]
    spec = importlib.util.spec_from_file_location(
        "render_outputs", ROOT / "scripts" / "render_outputs.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look the module up
    spec.loader.exec_module(module)
    return module
