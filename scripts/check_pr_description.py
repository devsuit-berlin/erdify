"""Check that a pull request description fills in its template.

Used by the ``pr-description.yml`` workflow. A release PR (title ``chore:
release X.Y.Z``) must fill in ``.github/release-pr-template.md``, every
other PR ``.github/PULL_REQUEST_TEMPLATE.md``. Template comments
(``<!-- ... -->``) and fenced code blocks don't count as headings.
Exits with status 1 and lists what is missing.

Run: ``PR_TITLE=... PR_BODY=... python scripts/check_pr_description.py``
"""

from __future__ import annotations

import os
import re
import sys

#: Sections that must have content of their own.
DEFAULT_REQUIRED = ("Summary", "Related issues", "How it was tested")
#: How many boxes a section needs ticked: "any" (at least one), "one" or "all".
DEFAULT_TICKED = {"Type of change": "any", "Output impact": "one"}

RELEASE_REQUIRED = ("Release", "What ships", "Highlights", "Upgrade impact")
RELEASE_TICKED = {"Release checklist": "all"}

_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
#: A fenced code block, also indented in a list item; an opening line with
#: more backticks after the fence is inline code, not a fence.
_FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,})[^`\n]*\n.*?^[ \t]*\1[ \t]*$", re.DOTALL | re.MULTILINE)
_HEADING = re.compile(r"^##[ \t]+(.+?)[ \t]*$", re.MULTILINE)
_TICKED = re.compile(r"^[ \t]*[-*][ \t]+\[[xX]\]", re.MULTILINE)
_UNTICKED = re.compile(r"^[ \t]*[-*][ \t]+\[ \]", re.MULTILINE)
#: The release type's reason, which must not be left empty.
_WHY = re.compile(r"\*\*Why this type:\*\*[ \t]*\S")
#: Release template placeholders that mean "not filled in".
_PLACEHOLDERS = ("X.Y.Z", "#PR — short description", "patch / minor / major")


def is_release(title: str) -> bool:
    """Whether the PR is a release PR (``chore: release X.Y.Z``)."""
    pattern = r"^chore(\(.*\))?:\s*release\s+v?\d+\.\d+\.\d+\b"
    return re.match(pattern, title.strip(), re.IGNORECASE) is not None


def sections(body: str) -> dict[str, str]:
    """``## Heading`` -> its text; comments and code blocks removed, the first heading wins."""
    text = _FENCE.sub("", _COMMENT.sub("", body.replace("\r\n", "\n")))
    found: dict[str, str] = {}
    matches = list(_HEADING.finditer(text))
    for match, following in zip(matches, [*matches[1:], None]):
        end = following.start() if following is not None else len(text)
        found.setdefault(match.group(1), text[match.end() : end].strip())
    return found


def problems(title: str, body: str) -> list[str]:
    """What the description is missing; empty when it is complete."""
    release = is_release(title)
    required, ticked = (
        (RELEASE_REQUIRED, RELEASE_TICKED) if release else (DEFAULT_REQUIRED, DEFAULT_TICKED)
    )
    template = ".github/release-pr-template.md" if release else ".github/PULL_REQUEST_TEMPLATE.md"
    found = sections(body or "")
    missing: list[str] = []
    for name in required:
        text = found.get(name)
        if text is None:
            missing.append(f"section '## {name}' is missing")
        elif not text:
            missing.append(f"section '## {name}' is empty")
        elif release and any(placeholder in text for placeholder in _PLACEHOLDERS):
            missing.append(f"section '## {name}' still has template placeholders")
        elif release and name == "Release" and not _WHY.search(text):
            missing.append("section '## Release' doesn't say why this release type")
    for name, rule in ticked.items():
        text = found.get(name)
        if text is None:
            missing.append(f"section '## {name}' is missing")
            continue
        count = len(_TICKED.findall(text))
        if count == 0:
            missing.append(f"section '## {name}' has no ticked box")
        elif rule == "one" and count > 1:
            missing.append(f"section '## {name}' must have exactly one ticked box")
        elif rule == "all" and _UNTICKED.search(text):
            missing.append(f"section '## {name}' has unticked boxes")
    if missing:
        missing.append(f"Fill in the template: {template}")
    return missing


def main() -> int:
    title = os.environ.get("PR_TITLE", "")
    body = os.environ.get("PR_BODY", "")
    found = problems(title, body)
    for problem in found:
        print(f"::error::{problem}")
    if not found:
        print("The PR description fills in its template.")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
