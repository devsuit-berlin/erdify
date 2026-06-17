"""Tests for path-based scan filtering (#43).

Filtering happens during the ``os.walk`` scan, before parsing: known
non-project dirs (site-packages, .venv, …) are pruned from the traversal, and
``--exclude-paths`` drops project folders by path/segment glob.
"""

import os
from pathlib import Path

import erdify.parser as parser_mod
from erdify.parser import parse_models_directory


class TestDefaultAutoSkip:
    def test_site_packages_skipped_by_default(self, scan_filter_dir: Path):
        entities, _ = parse_models_directory(scan_filter_dir)

        assert "Widget" in entities
        assert "LegacyThing" in entities
        assert "ThirdPartyModel" not in entities

    def test_no_default_excludes_includes_site_packages(self, scan_filter_dir: Path):
        entities, _ = parse_models_directory(scan_filter_dir, use_default_excludes=False)

        assert "ThirdPartyModel" in entities


class TestExcludePaths:
    def test_segment_pattern_skips_folder(self, scan_filter_dir: Path):
        entities, _ = parse_models_directory(scan_filter_dir, exclude_paths=["legacy"])

        assert "Widget" in entities
        assert "LegacyThing" not in entities

    def test_full_path_glob_skips_folder(self, scan_filter_dir: Path):
        entities, _ = parse_models_directory(scan_filter_dir, exclude_paths=["app/*"])

        assert "Widget" not in entities
        assert "LegacyThing" in entities

    def test_exclude_paths_combine_with_default(self, scan_filter_dir: Path):
        entities, _ = parse_models_directory(scan_filter_dir, exclude_paths=["legacy"])

        # Default auto-skip still applies alongside an explicit exclude.
        assert "ThirdPartyModel" not in entities


class TestWalkPruning:
    """Excluded dirs must be pruned *during* the walk, not filtered afterwards.

    Filtering after a full ``rglob`` still scandirs huge trees like ``.venv``
    (which can hold thousands of dirs) before discarding them. Pruning before
    descending keeps the scan proportional to the project, not the venv.
    """

    _WIDGET = "from dataclasses import dataclass\n\n\n@dataclass\nclass Widget:\n    id: int\n"
    _JUNK = "from dataclasses import dataclass\n\n\n@dataclass\nclass Junk:\n    id: int\n"

    def _make_tree(self, root: Path) -> None:
        (root / "app").mkdir()
        (root / "app" / "models.py").write_text(self._WIDGET)
        # Heavy excluded subtree that must never be descended into.
        venv_deep = root / ".venv" / "lib" / "python" / "site-packages" / "pkg"
        venv_deep.mkdir(parents=True)
        (venv_deep / "models.py").write_text(self._JUNK)

    def test_excluded_dirs_are_not_descended(self, tmp_path: Path, monkeypatch) -> None:
        self._make_tree(tmp_path)

        visited: list[str] = []
        real_walk = os.walk

        def spy_walk(top, *args, **kwargs):
            for root, dirs, files in real_walk(top, *args, **kwargs):
                visited.append(root)
                yield root, dirs, files

        monkeypatch.setattr(parser_mod.os, "walk", spy_walk)

        entities, _ = parse_models_directory(tmp_path)

        # Discovery must go through os.walk (red on the old rglob implementation).
        assert visited, "expected os.walk-based discovery"
        # The project model is found; the venv model is not.
        assert "Widget" in entities
        assert "Junk" not in entities
        # The walk never descends into the pruned tree.
        assert not any(".venv" in Path(root).parts for root in visited)

    def test_no_default_excludes_still_descends(self, tmp_path: Path) -> None:
        self._make_tree(tmp_path)

        entities, _ = parse_models_directory(tmp_path, use_default_excludes=False)

        # Without default excludes, the venv subtree is scanned and parsed.
        assert "Widget" in entities
        assert "Junk" in entities
