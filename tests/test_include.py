from pathlib import Path

from erdify.parser import _match_include, _translate_glob, parse_models_directory
import re


def _matches(pattern: str, rel_path: str) -> bool:
    return re.match(_translate_glob(pattern), rel_path) is not None


class TestTranslateGlob:
    def test_star_does_not_cross_slash(self):
        assert _matches("app/*.py", "app/models.py")
        assert not _matches("app/*.py", "app/sub/models.py")

    def test_double_star_crosses_slashes_including_zero(self):
        assert _matches("**/models/*.py", "models/user.py")
        assert _matches("**/models/*.py", "a/b/models/user.py")

    def test_double_star_inner_dir_not_crossed_by_single_star(self):
        # *.py after models/ must not match a nested file
        assert not _matches("**/models/*.py", "models/sub/user.py")

    def test_question_mark_one_non_slash_char(self):
        assert _matches("v?.py", "v1.py")
        assert not _matches("v?.py", "v12.py")


class TestMatchInclude:
    def test_slashless_matches_basename_any_depth(self):
        assert _match_include("a/b/models.py", "models.py", ["models.py"])
        assert _match_include("x/statistics_models.py", "statistics_models.py", ["*_models.py"])

    def test_slashless_does_not_match_other_names(self):
        assert not _match_include("a/tables.py", "tables.py", ["models.py"])

    def test_slash_pattern_matches_relative_path(self):
        assert _match_include("app/models/user.py", "user.py", ["**/models/*.py"])

    def test_no_patterns_no_match(self):
        assert not _match_include("a/models.py", "models.py", [])


_DC = "from dataclasses import dataclass\n\n\n@dataclass\nclass {name}:\n    id: int\n"


def _make(root: Path, rel: str, name: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_DC.format(name=name))


class TestIncludeDiscovery:
    def test_default_finds_only_models_py(self, tmp_path: Path):
        _make(tmp_path, "app/models.py", "Widget")
        _make(tmp_path, "app/models/order.py", "Order")  # package file: ignored
        entities, _ = parse_models_directory(tmp_path)
        assert "Widget" in entities
        assert "Order" not in entities

    def test_slash_pattern_finds_models_package(self, tmp_path: Path):
        _make(tmp_path, "app/models/order.py", "Order")
        _make(tmp_path, "app/models/user.py", "User")
        entities, _ = parse_models_directory(tmp_path, include_patterns=["**/models/*.py"])
        assert {"Order", "User"} <= set(entities)

    def test_replace_semantics_drops_models_py(self, tmp_path: Path):
        _make(tmp_path, "app/models.py", "Widget")
        _make(tmp_path, "app/tables.py", "Thing")
        entities, _ = parse_models_directory(tmp_path, include_patterns=["tables.py"])
        assert "Thing" in entities
        assert "Widget" not in entities  # models.py no longer matched

    def test_combined_patterns(self, tmp_path: Path):
        _make(tmp_path, "app/models.py", "Widget")
        _make(tmp_path, "app/models/order.py", "Order")
        entities, _ = parse_models_directory(
            tmp_path, include_patterns=["models.py", "**/models/*.py"]
        )
        assert {"Widget", "Order"} <= set(entities)

    def test_exclude_paths_still_applies(self, tmp_path: Path):
        _make(tmp_path, "app/models/order.py", "Order")
        _make(tmp_path, "legacy/models/old.py", "Old")
        entities, _ = parse_models_directory(
            tmp_path, include_patterns=["**/models/*.py"], exclude_paths=["legacy"]
        )
        assert "Order" in entities
        assert "Old" not in entities

    def test_default_dir_pruning_still_applies(self, tmp_path: Path):
        _make(tmp_path, "app/models/order.py", "Order")
        _make(tmp_path, ".venv/lib/models/junk.py", "Junk")
        entities, _ = parse_models_directory(tmp_path, include_patterns=["**/models/*.py"])
        assert "Order" in entities
        assert "Junk" not in entities
