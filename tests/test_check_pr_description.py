"""The PR description check run by pr-description.yml (scripts/check_pr_description.py)."""

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "check_pr_description", ROOT / "scripts" / "check_pr_description.py"
)
assert _spec is not None and _spec.loader is not None
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)

DEFAULT = (ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md").read_text(encoding="utf-8")
RELEASE = (ROOT / ".github" / "release-pr-template.md").read_text(encoding="utf-8")


def _fill(template: str, texts: dict[str, str], tick: tuple[str, ...]) -> str:
    """The template with text after the given headings and the given boxes ticked."""
    body = template
    for heading, text in texts.items():
        body = body.replace(f"## {heading}\n", f"## {heading}\n\n{text}\n", 1)
    for label in tick:
        body = body.replace(f"- [ ] {label}", f"- [x] {label}", 1)
    return body


def _filled_default() -> str:
    return _fill(
        DEFAULT,
        {
            "Summary": "Reads @declared_attr relationships.",
            "Related issues": "Closes #298",
            "How it was tested": "tests/test_declared_attr.py, ground truth.",
        },
        ("Bug fix", "Output changes"),
    )


def test_blank_template_fails_on_every_section() -> None:
    found = check.problems("fix: something", DEFAULT)
    assert found == [
        "section '## Summary' is empty",
        "section '## Related issues' is empty",
        "section '## How it was tested' is empty",
        "section '## Type of change' has no ticked box",
        "section '## Output impact' has no ticked box",
        "Fill in the template: .github/PULL_REQUEST_TEMPLATE.md",
    ]


def test_filled_template_passes() -> None:
    assert check.problems("fix: something", _filled_default()) == []


def test_windows_line_endings_and_uppercase_x() -> None:
    body = _filled_default().replace("- [x] Bug fix", "- [X] Bug fix").replace("\n", "\r\n")
    assert check.problems("fix: something", body) == []


def test_empty_or_foreign_body_lists_missing_sections() -> None:
    found = check.problems("feat: x", "Some text without the template.")
    assert "section '## Summary' is missing" in found
    assert check.problems("feat: x", "")[0] == "section '## Summary' is missing"


def test_release_titles() -> None:
    assert check.is_release("chore: release 1.4.5")
    assert check.is_release("chore(release): release v2.0.0")
    assert not check.is_release("chore: release PR template")
    assert not check.is_release("chore: release-please config")
    assert not check.is_release("fix: release notes typo")
    assert not check.is_release("chore: bump deps")


def test_blank_release_template_fails() -> None:
    found = check.problems("chore: release 1.4.5", RELEASE)
    assert "section '## Release' still has template placeholders" in found
    assert "section '## What ships' still has template placeholders" in found
    assert "section '## Highlights' is empty" in found
    assert "section '## Release checklist' has no ticked box" in found
    assert found[-1] == "Fill in the template: .github/release-pr-template.md"


def test_filled_release_template_passes() -> None:
    body = re.sub(
        r"## Release\n.*?\n## What ships\n.*?\n- #PR — short description \(closes #…\)\n",
        "## Release\n\n- **Version:** 1.4.5 (previous: 1.4.4)\n"
        "- **Type:** patch\n- **Why this type:** fixes only\n\n"
        "## What ships\n\n- #320 — batch D (closes #298)\n",
        RELEASE,
        flags=re.DOTALL,
    )
    body = _fill(
        body,
        {"Highlights": "- Inheritance drawn like SQLAlchemy", "Upgrade impact": "Output changes."},
        (),
    )
    body = body.replace("- [ ] ", "- [x] ")
    assert check.problems("chore: release 1.4.5", body) == []
    partly = body.replace("- [x] CI green", "- [ ] CI green")
    assert check.problems("chore: release 1.4.5", partly)[0] == (
        "section '## Release checklist' has unticked boxes"
    )
    no_why = body.replace("- **Why this type:** fixes only", "- **Why this type:**")
    assert "section '## Release' doesn't say why this release type" in check.problems(
        "chore: release 1.4.5", no_why
    )


def test_main_reports_errors(monkeypatch, capsys) -> None:
    monkeypatch.setenv("PR_TITLE", "fix: x")
    monkeypatch.setenv("PR_BODY", DEFAULT)
    assert check.main() == 1
    assert "::error::section '## Summary' is empty" in capsys.readouterr().out
    monkeypatch.setenv("PR_BODY", _filled_default())
    assert check.main() == 0


def test_release_type_left_open_fails() -> None:
    body = RELEASE.replace("X.Y.Z (previous: X.Y.Z)", "1.4.5 (previous: 1.4.4)")
    assert "section '## Release' still has template placeholders" in check.problems(
        "chore: release 1.4.5", body
    )


def test_headings_in_code_blocks_do_not_split_sections() -> None:
    pasted = "```markdown\n## Summary\n\n## [1.4.5] - 2026-11-12\n```"
    body = _filled_default().replace(
        "tests/test_declared_attr.py, ground truth.", f"Rendered:\n{pasted}"
    )
    assert check.problems("fix: something", body) == []
    assert check.sections(body)["Summary"] == "Reads @declared_attr relationships."


def test_placeholders_only_count_in_release_prs() -> None:
    body = _filled_default().replace(
        "Reads @declared_attr relationships.", "Documents `chore: release X.Y.Z` titles."
    )
    assert check.problems("docs: release flow", body) == []


def test_output_impact_needs_exactly_one_box() -> None:
    body = _filled_default().replace("- [ ] Breaking", "- [x] Breaking")
    assert check.problems("fix: something", body)[0] == (
        "section '## Output impact' must have exactly one ticked box"
    )


def test_inline_code_and_indented_fences() -> None:
    body = _filled_default().replace(
        "Reads @declared_attr relationships.",
        "Reads @declared_attr relationships.\n```uv run pytest```",
    )
    body = body.replace(
        "tests/test_declared_attr.py, ground truth.",
        "- step\n  ```markdown\n  ## Summary\n  ```\n\n```text\nlog\n```",
    )
    assert check.problems("fix: something", body) == []


def test_bare_heading_marker_does_not_take_the_next_line() -> None:
    body = "##\nSummary\n" + _filled_default()
    assert check.sections(body)["Summary"] == "Reads @declared_attr relationships."
