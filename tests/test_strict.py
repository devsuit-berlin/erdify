"""Strict mode: a file that cannot be parsed fails the run instead of being skipped."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from erdify import ASTDatabaseParser, ModelParseError, SqlSchemaParser, parse_models_directory
from erdify.cli import main

VALID_MODEL = (
    "from sqlmodel import Field, SQLModel\n\n\n"
    "class User(SQLModel, table=True):\n"
    "    id: int | None = Field(default=None, primary_key=True)\n"
)


@pytest.fixture
def mixed_tree(tmp_path: Path) -> Path:
    """One valid models.py, one with a syntax error, one broken .sql file."""
    (tmp_path / "good").mkdir()
    (tmp_path / "good" / "models.py").write_text(VALID_MODEL)
    (tmp_path / "bad").mkdir()
    (tmp_path / "bad" / "models.py").write_text("class Broken(:\n")
    (tmp_path / "schema.sql").write_text("CREATE TABLE (")
    return tmp_path


class TestDefaultIsLenient:
    def test_broken_file_is_skipped(self, mixed_tree: Path, capsys):
        entities, _ = parse_models_directory(mixed_tree, include_patterns=["models.py", "*.sql"])

        assert set(entities) == {"User"}
        err = capsys.readouterr().err
        assert "Error parsing" in err and "bad" in err


class TestStrictParseModelsDirectory:
    def test_raises_with_python_and_sql_failures(self, mixed_tree: Path, capsys):
        with pytest.raises(ModelParseError) as exc_info:
            parse_models_directory(mixed_tree, include_patterns=["models.py", "*.sql"], strict=True)

        failed = [path.name for path, _ in exc_info.value.errors]
        assert failed == ["models.py", "schema.sql"]
        assert "2 file(s) could not be parsed" in str(exc_info.value)
        # Every failure is still reported on stderr as it happens.
        assert capsys.readouterr().err.count("Error parsing") == 2

    def test_clean_input_is_unaffected(self, sample_models_dir: Path):
        lenient, _ = parse_models_directory(sample_models_dir)
        strict, _ = parse_models_directory(sample_models_dir, strict=True)

        assert set(strict) == set(lenient)


class TestStrictClasses:
    def test_ast_parser(self, mixed_tree: Path):
        with pytest.raises(ModelParseError) as exc_info:
            ASTDatabaseParser(mixed_tree, strict=True).parse_all_models()

        assert [p.parent.name for p, _ in exc_info.value.errors] == ["bad"]

    def test_sql_parser(self, mixed_tree: Path):
        with pytest.raises(ModelParseError):
            SqlSchemaParser([mixed_tree / "schema.sql"], strict=True).parse()

    def test_sql_parser_lenient_by_default(self, mixed_tree: Path):
        entities, _ = SqlSchemaParser([mixed_tree / "schema.sql"]).parse()

        assert entities == {}


class TestUnreadableSqlFile:
    """A .sql file that is not valid UTF-8 is a per-file failure, not a crash."""

    @pytest.fixture
    def sql_tree(self, tmp_path: Path) -> Path:
        (tmp_path / "a.sql").write_text("CREATE TABLE ok (id INT PRIMARY KEY);")
        (tmp_path / "b.sql").write_bytes(b"CREATE TABLE \xff\xfe bad (id INT);")
        (tmp_path / "models.py").write_text("class Broken(:\n")
        return tmp_path

    def test_lenient_skips_it_and_keeps_the_rest(self, sql_tree: Path, capsys):
        entities, _ = parse_models_directory(sql_tree, include_patterns=["models.py", "*.sql"])

        assert set(entities) == {"ok"}
        assert "b.sql" in capsys.readouterr().err

    def test_strict_aggregates_it_with_python_failures(self, sql_tree: Path):
        with pytest.raises(ModelParseError) as exc_info:
            parse_models_directory(sql_tree, include_patterns=["models.py", "*.sql"], strict=True)

        assert [p.name for p, _ in exc_info.value.errors] == ["models.py", "b.sql"]


class TestStrictCLI:
    def test_flag_exits_one_and_writes_nothing(self, mixed_tree: Path, tmp_path: Path, capsys):
        out = tmp_path / "erd.puml"
        argv = ["erdify", str(mixed_tree), "-o", str(out), "--strict"]
        with patch.object(sys, "argv", argv):
            assert main() == 1

        assert not out.exists()
        assert "could not be parsed (strict mode)" in capsys.readouterr().err

    def test_without_flag_exits_zero(self, mixed_tree: Path, tmp_path: Path):
        out = tmp_path / "erd.puml"
        with patch.object(sys, "argv", ["erdify", str(mixed_tree), "-o", str(out)]):
            assert main() == 0

        assert out.exists()

    def test_config_key(self, mixed_tree: Path, tmp_path: Path):
        (mixed_tree / "pyproject.toml").write_text("[tool.erdify]\nstrict = true\n")
        out = tmp_path / "erd.puml"
        with patch.object(sys, "argv", ["erdify", str(mixed_tree), "-o", str(out)]):
            assert main() == 1

        assert not out.exists()
