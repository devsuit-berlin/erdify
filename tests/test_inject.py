import pytest

from erdify.inject import (
    MARKER_END,
    MARKER_START,
    MarkerError,
    current_region,
    inject,
    render_region,
)

_DOC = f"# Title\n\nintro\n\n{MARKER_START}\nOLD\n{MARKER_END}\n\noutro\n"


class TestRenderRegion:
    def test_wraps_in_fence_with_tag(self):
        assert render_region("erDiagram\n  A", "mermaid") == "\n```mermaid\nerDiagram\n  A\n```\n"

    def test_normalizes_trailing_newlines(self):
        assert render_region("X\n\n\n", "json") == "\n```json\nX\n```\n"


class TestInject:
    def test_replaces_only_region_and_preserves_surroundings(self):
        block = render_region("erDiagram", "mermaid")
        out = inject(_DOC, block)
        assert out.startswith("# Title\n\nintro\n\n" + MARKER_START)
        assert out.endswith(MARKER_END + "\n\noutro\n")
        assert "OLD" not in out
        assert "```mermaid\nerDiagram\n```" in out

    def test_idempotent(self):
        block = render_region("erDiagram", "mermaid")
        once = inject(_DOC, block)
        assert inject(once, block) == once

    def test_missing_start_marker_raises(self):
        with pytest.raises(MarkerError):
            inject(f"no markers here\n{MARKER_END}\n", "x")

    def test_missing_end_marker_raises(self):
        with pytest.raises(MarkerError):
            inject(f"{MARKER_START}\nonly start\n", "x")

    def test_reversed_markers_raise(self):
        with pytest.raises(MarkerError):
            inject(f"{MARKER_END}\nx\n{MARKER_START}\n", "x")

    def test_duplicate_markers_raise(self):
        with pytest.raises(MarkerError):
            inject(f"{MARKER_START}\na\n{MARKER_END}\n{MARKER_START}\nb\n{MARKER_END}\n", "x")


class TestCurrentRegion:
    def test_returns_inner_text(self):
        assert current_region(_DOC) == "\nOLD\n"

    def test_raises_without_markers(self):
        with pytest.raises(MarkerError):
            current_region("# no markers\n")

    def test_round_trips_with_render_region(self):
        block = render_region("erDiagram", "mermaid")
        assert current_region(inject(_DOC, block)) == block


class TestAttributeMarkers:
    """Markers carrying attributes (e.g. id=db) must be matched leniently."""

    _DOC_ATTRS = "# Title\n\n<!-- erdify:start id=db -->\nOLD\n<!-- erdify:end id=db -->\n\noutro\n"

    def test_inject_with_attribute_markers(self):
        block = render_region("erDiagram", "mermaid")
        out = inject(self._DOC_ATTRS, block)
        # Markers with attributes are preserved verbatim
        assert "<!-- erdify:start id=db -->" in out
        assert "<!-- erdify:end id=db -->" in out
        assert "OLD" not in out
        assert "```mermaid\nerDiagram\n```" in out

    def test_current_region_with_attribute_markers(self):
        block = render_region("erDiagram", "mermaid")
        injected = inject(self._DOC_ATTRS, block)
        assert current_region(injected) == block
