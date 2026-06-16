"""Tests for path-based scan filtering (#43).

Filtering happens during the ``rglob("models.py")`` scan, before parsing:
known non-project dirs (site-packages, .venv, …) are auto-skipped, and
``--exclude-paths`` drops project folders by path/segment glob.
"""

from pathlib import Path

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
