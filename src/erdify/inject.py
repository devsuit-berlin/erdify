"""Inject a rendered ERD into a markdown file, between erdify marker comments.

Only the text between the markers is replaced; every other byte of the file is
preserved. Matching is lenient (tolerates whitespace and future attributes) so
the single-region format stays forward-compatible.
"""

import re

#: Canonical markers erdify emits. Matching also accepts attributes/whitespace.
MARKER_START = "<!-- erdify:start -->"
MARKER_END = "<!-- erdify:end -->"

_START_RE = re.compile(r"<!--\s*erdify:start\b[^>]*-->")
_END_RE = re.compile(r"<!--\s*erdify:end\b[^>]*-->")


class MarkerError(Exception):
    """Raised when a markdown file lacks a well-formed erdify marker region."""


def _find_markers(text: str) -> tuple[int, int]:
    """Return (end-of-start-marker offset, start-of-end-marker offset).

    Raises MarkerError if the markers are missing, duplicated, or reversed.
    """
    starts = list(_START_RE.finditer(text))
    ends = list(_END_RE.finditer(text))
    if not starts:
        raise MarkerError(f"no '{MARKER_START}' marker found")
    if not ends:
        raise MarkerError(f"no '{MARKER_END}' marker found")
    if len(starts) > 1 or len(ends) > 1:
        raise MarkerError("multiple erdify marker pairs found; expected exactly one")
    start, end = starts[0], ends[0]
    if end.start() < start.end():
        raise MarkerError("erdify:end marker appears before erdify:start")
    return start.end(), end.start()


def render_region(rendered: str, fence: str) -> str:
    """Wrap a rendered ERD as a fenced code block to place between the markers."""
    return "\n```" + fence + "\n" + rendered.rstrip("\n") + "\n```\n"


def inject(file_text: str, block: str) -> str:
    """Replace the text between the markers with ``block``.

    The markers and everything outside them are preserved. Raises MarkerError
    on any marker problem.
    """
    start_close, end_open = _find_markers(file_text)
    return file_text[:start_close] + block + file_text[end_open:]


def current_region(file_text: str) -> str:
    """Return the text currently between the markers (for --check comparison)."""
    start_close, end_open = _find_markers(file_text)
    return file_text[start_close:end_open]
