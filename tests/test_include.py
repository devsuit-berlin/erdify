from erdify.parser import _match_include, _translate_glob
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
