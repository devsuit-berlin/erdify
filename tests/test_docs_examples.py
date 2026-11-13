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


def test_worked_example_shows_the_real_output(tmp_path: Path) -> None:
    """The Frameworks page's worked example shows what erdify draws for its models.

    ``docs/examples/example_erd.png`` is a PlantUML rendering of that block;
    re-render it when the block changes.
    """
    page = (EXAMPLES.parent / "frameworks" / "index.md").read_text(encoding="utf-8")
    section = page.split("## Worked example", 1)[1]
    models = section.split("```python\n", 1)[1].split("\n```", 1)[0]
    shown = section.split("```plantuml\n", 1)[1].split("\n```", 1)[0]
    (tmp_path / "models.py").write_text(models + "\n", encoding="utf-8")
    out = tmp_path / "erd.puml"
    with patch.object(sys, "argv", ["erdify", str(tmp_path), "-o", str(out)]):
        assert main() == 0
    assert out.read_text(encoding="utf-8").rstrip("\n") == shown
