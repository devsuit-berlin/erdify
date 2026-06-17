"""Tests for CLI module."""

from pathlib import Path
from unittest.mock import patch
import sys

import pytest

from erdify.cli import main


class TestCLI:
    """Tests for CLI functionality."""

    def test_cli_with_output_file(self, sample_models_dir: Path, temp_dir: Path):
        """Test CLI with output file."""
        output_file = temp_dir / "output.puml"

        with patch.object(sys, "argv", ["erdify", str(sample_models_dir), "-o", str(output_file)]):
            result = main()

        assert result == 0
        assert output_file.exists()
        content = output_file.read_text()
        assert "@startuml" in content
        assert "@enduml" in content

    def test_cli_stdout(self, sample_models_dir: Path, capsys):
        """Test CLI output to stdout."""
        with patch.object(sys, "argv", ["erdify", str(sample_models_dir)]):
            result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "@startuml" in captured.out
        assert "@enduml" in captured.out

    def test_cli_custom_title(self, sample_models_dir: Path, capsys):
        """Test CLI with custom title."""
        with patch.object(sys, "argv", ["erdify", str(sample_models_dir), "--title", "My ERD"]):
            result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "@startuml My ERD" in captured.out

    def test_cli_nonexistent_path(self, temp_dir: Path, capsys):
        """Test CLI with nonexistent input path."""
        nonexistent = temp_dir / "does_not_exist"

        with patch.object(sys, "argv", ["erdify", str(nonexistent)]):
            result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "does not exist" in captured.err

    def test_cli_file_instead_of_dir(self, sample_models_dir: Path, capsys):
        """Test CLI with file instead of directory."""
        file_path = sample_models_dir / "models.py"

        with patch.object(sys, "argv", ["erdify", str(file_path)]):
            result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "not a directory" in captured.err

    def test_cli_creates_output_dir(self, sample_models_dir: Path, temp_dir: Path):
        """Test that CLI creates output directory if needed."""
        output_file = temp_dir / "nested" / "dir" / "output.puml"

        with patch.object(sys, "argv", ["erdify", str(sample_models_dir), "-o", str(output_file)]):
            result = main()

        assert result == 0
        assert output_file.exists()

    def test_cli_no_enums_flag(self, sample_models_dir: Path, capsys):
        """Test CLI with --no-enums flag."""
        with patch.object(sys, "argv", ["erdify", str(sample_models_dir), "--no-enums"]):
            result = main()

        assert result == 0
        captured = capsys.readouterr()
        # Enum definitions should not be present
        assert "enum UserRole" not in captured.out

    def test_cli_exclude_pattern(self, sample_models_dir: Path, capsys):
        """Test CLI --exclude removes matching entities from output."""
        with patch.object(sys, "argv", ["erdify", str(sample_models_dir), "--exclude", "*Link"]):
            result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "UserProductLink" not in captured.out
        assert "as User " in captured.out or "as User{" in captured.out

    def test_cli_sources_filter(self, sample_models_dir: Path, capsys):
        """--sources restricts output to the given model kinds."""
        with patch.object(sys, "argv", ["erdify", str(sample_models_dir), "--sources", "sqlmodel"]):
            result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "as User " in captured.out or "as User{" in captured.out

    def test_cli_sources_rejects_unknown_kind(self, sample_models_dir: Path):
        """argparse choices reject an unknown model kind (exits non-zero)."""
        with patch.object(sys, "argv", ["erdify", str(sample_models_dir), "--sources", "nonsense"]):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code != 0

    def test_cli_infer_keys_pydantic(self, pydantic_models_dir: Path, capsys):
        """--infer-keys turns id/<x>_id into keys for Pydantic models."""
        with patch.object(sys, "argv", ["erdify", str(pydantic_models_dir), "--infer-keys"]):
            result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "primary_key(id)" in captured.out
        assert "foreign_key(customer_id)" in captured.out

    def test_cli_django_default_maps_python_types(self, django_models_dir: Path, capsys):
        """By default Django field types render as Python types."""
        with patch.object(sys, "argv", ["erdify", str(django_models_dir)]):
            result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "column(name) : str" in captured.out
        assert "CharField" not in captured.out

    def test_cli_django_raw_types(self, django_models_dir: Path, capsys):
        """--django-raw-types keeps the original Django field names."""
        with patch.object(sys, "argv", ["erdify", str(django_models_dir), "--django-raw-types"]):
            result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "column(name) : CharField" in captured.out

    def test_cli_auto_skips_site_packages(self, scan_filter_dir: Path, capsys):
        """By default models.py under site-packages is skipped."""
        with patch.object(sys, "argv", ["erdify", str(scan_filter_dir)]):
            result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "Widget" in captured.out
        assert "ThirdPartyModel" not in captured.out

    def test_cli_exclude_paths(self, scan_filter_dir: Path, capsys):
        """--exclude-paths skips a project folder by segment."""
        with patch.object(
            sys, "argv", ["erdify", str(scan_filter_dir), "--exclude-paths", "legacy"]
        ):
            result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "LegacyThing" not in captured.out

    def test_cli_no_default_excludes(self, scan_filter_dir: Path, capsys):
        """--no-default-excludes scans site-packages too."""
        with patch.object(sys, "argv", ["erdify", str(scan_filter_dir), "--no-default-excludes"]):
            result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "ThirdPartyModel" in captured.out

    def test_cli_format_mermaid_stdout(self, sample_models_dir: Path, capsys):
        """--format mermaid emits an erDiagram to stdout."""
        with patch.object(sys, "argv", ["erdify", str(sample_models_dir), "--format", "mermaid"]):
            assert main() == 0
        assert capsys.readouterr().out.lstrip().startswith("erDiagram")

    def test_cli_format_both_writes_two_files(self, sample_models_dir: Path, temp_dir: Path):
        """--format plantuml mermaid writes <base>.puml and <base>.mmd."""
        base = temp_dir / "erd.puml"
        with patch.object(
            sys,
            "argv",
            ["erdify", str(sample_models_dir), "-o", str(base), "--format", "plantuml", "mermaid"],
        ):
            assert main() == 0
        assert (temp_dir / "erd.puml").exists()
        assert (temp_dir / "erd.mmd").exists()

    def test_cli_output_extension_normalized(self, sample_models_dir: Path, temp_dir: Path):
        """The output extension is forced to match the format."""
        with patch.object(
            sys,
            "argv",
            [
                "erdify",
                str(sample_models_dir),
                "-o",
                str(temp_dir / "erd.txt"),
                "--format",
                "mermaid",
            ],
        ):
            assert main() == 0
        assert (temp_dir / "erd.mmd").exists()
        assert not (temp_dir / "erd.txt").exists()

    def test_cli_format_json_writes_valid_json(self, sample_models_dir: Path, temp_dir: Path):
        """--format json writes a parseable .json file."""
        import json as _json

        with patch.object(
            sys,
            "argv",
            ["erdify", str(sample_models_dir), "-o", str(temp_dir / "erd"), "--format", "json"],
        ):
            assert main() == 0
        data = _json.loads((temp_dir / "erd.json").read_text())
        assert "entities" in data

    def test_cli_format_html_writes_page(self, sample_models_dir: Path, temp_dir: Path):
        """--format html writes a self-contained .html page."""
        with patch.object(
            sys,
            "argv",
            ["erdify", str(sample_models_dir), "-o", str(temp_dir / "erd"), "--format", "html"],
        ):
            assert main() == 0
        assert '<pre class="mermaid">' in (temp_dir / "erd.html").read_text()

    def test_cli_multiple_formats_require_output(self, sample_models_dir: Path, capsys):
        """Multiple formats to stdout is an error."""
        with patch.object(
            sys, "argv", ["erdify", str(sample_models_dir), "--format", "plantuml", "mermaid"]
        ):
            assert main() != 0
        assert "--output" in capsys.readouterr().err

    def test_cli_pydantic_without_infer_keys(self, pydantic_models_dir: Path, capsys):
        """Without --infer-keys, Pydantic id/<x>_id stay plain columns."""
        with patch.object(sys, "argv", ["erdify", str(pydantic_models_dir)]):
            result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "foreign_key(customer_id)" not in captured.out

    def test_cli_empty_models_warning(self, empty_models_dir: Path, capsys):
        """Test CLI warns when no tables found."""
        with patch.object(sys, "argv", ["erdify", str(empty_models_dir)]):
            result = main()

        assert result == 0  # Not an error, just a warning
        captured = capsys.readouterr()
        assert "No tables found" in captured.err


class TestCLIVersion:
    """Tests for version reporting (single-sourced from package metadata)."""

    def test_version_matches_metadata(self):
        """__version__ is read from the installed package metadata."""
        from importlib.metadata import version

        import erdify

        assert erdify.__version__ == version("erdify")

    def test_cli_version_flag(self, capsys):
        """--version prints the package version and exits cleanly."""
        import erdify

        with patch.object(sys, "argv", ["erdify", "--version"]):
            with pytest.raises(SystemExit) as exc:
                main()

        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert erdify.__version__ in captured.out


class TestCLIIntegration:
    """Integration tests for CLI."""

    def test_full_workflow(self, sample_models_dir: Path, temp_dir: Path):
        """Test complete workflow from parsing to output."""
        output_file = temp_dir / "erd.puml"

        with patch.object(
            sys,
            "argv",
            [
                "erdify",
                str(sample_models_dir),
                "-o",
                str(output_file),
                "--title",
                "Test Database",
            ],
        ):
            result = main()

        assert result == 0
        assert output_file.exists()

        content = output_file.read_text()

        # Verify structure
        assert "@startuml Test Database" in content
        assert "@enduml" in content

        # Verify entities
        assert 'entity "user" as User' in content
        assert 'entity "order" as Order' in content

        # Verify fields
        assert "primary_key(id)" in content
        assert "foreign_key(user_id)" in content

        # Verify relationships section exists
        assert "' Relationships" in content


_DC_CLI = "from dataclasses import dataclass\n\n\n@dataclass\nclass {name}:\n    id: int\n"


def test_include_flag_finds_models_package(tmp_path, capsys):
    (tmp_path / "app" / "models").mkdir(parents=True)
    (tmp_path / "app" / "models" / "order.py").write_text(_DC_CLI.format(name="Order"))
    with patch.object(sys, "argv", ["erdify", str(tmp_path), "--include", "**/models/*.py"]):
        rc = main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "Order" in out


def test_include_config_key(tmp_path, capsys):
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "user.py").write_text(_DC_CLI.format(name="User"))
    (tmp_path / "pyproject.toml").write_text('[tool.erdify]\ninclude = ["**/models/*.py"]\n')
    with patch.object(sys, "argv", ["erdify", str(tmp_path)]):
        rc = main()
    assert rc == 0
    assert "User" in capsys.readouterr().out


def test_include_cli_overrides_config(tmp_path, capsys):
    # Config would scan the package; the explicit CLI flag replaces it with tables.py.
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "user.py").write_text(_DC_CLI.format(name="User"))
    (tmp_path / "tables.py").write_text(_DC_CLI.format(name="Thing"))
    (tmp_path / "pyproject.toml").write_text('[tool.erdify]\ninclude = ["**/models/*.py"]\n')
    with patch.object(sys, "argv", ["erdify", str(tmp_path), "--include", "tables.py"]):
        rc = main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "Thing" in out  # CLI pattern wins
    assert "User" not in out  # config pattern not applied
