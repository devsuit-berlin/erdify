"""The docs examples render the committed diagram (#269).

``docs/examples/<framework>`` holds the same User / Order schema in each
framework, and the docs (README, Frameworks overview) promise that all of them
draw ``docs/examples/erd.puml``. Each one is run through the CLI with
``--check``, as a project gating CI on it would. The models themselves are
checked against the real frameworks by the ground-truth tests.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from erdify.cli import main

EXAMPLES = Path(__file__).resolve().parent.parent / "docs" / "examples"
DIAGRAM = EXAMPLES / "erd.puml"
TITLE = "Framework Comparison ERD"
# Pydantic and dataclasses have no keys; the examples' docstrings say to
# render them with --infer-keys to get the identical ERD.
KEYLESS = {"pydantic", "dataclass"}
FRAMEWORKS = sorted(p.name for p in EXAMPLES.iterdir() if p.is_dir())


def test_every_framework_has_an_example() -> None:
    assert FRAMEWORKS == ["dataclass", "django", "pydantic", "sqlalchemy", "sqlmodel"]


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_example_draws_the_committed_diagram(framework: str) -> None:
    argv = ["erdify", str(EXAMPLES / framework), "--title", TITLE, "-o", str(DIAGRAM), "--check"]
    if framework in KEYLESS:
        argv.append("--infer-keys")
    with patch.object(sys, "argv", argv):
        assert main() == 0, (
            f"docs/examples/{framework} no longer draws docs/examples/erd.puml. "
            f"Regenerate it with: erdify docs/examples/{framework} --title '{TITLE}'"
            f"{' --infer-keys' if framework in KEYLESS else ''} -o docs/examples/erd.puml"
        )
