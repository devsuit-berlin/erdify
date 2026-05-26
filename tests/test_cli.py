"""Tests for CLI module."""

from pathlib import Path
from unittest.mock import patch
import sys

from erdify.cli import main


class TestCLI:
    """Tests for CLI functionality."""

    def test_cli_with_output_file(self, sample_models_dir: Path, temp_dir: Path):
        """Test CLI with output file."""
        output_file = temp_dir / "output.puml"

        with patch.object(
            sys, "argv", ["erdify", str(sample_models_dir), "-o", str(output_file)]
        ):
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
        with patch.object(
            sys, "argv", ["erdify", str(sample_models_dir), "--title", "My ERD"]
        ):
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

        with patch.object(
            sys, "argv", ["erdify", str(sample_models_dir), "-o", str(output_file)]
        ):
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

    def test_cli_empty_models_warning(self, empty_models_dir: Path, capsys):
        """Test CLI warns when no tables found."""
        with patch.object(sys, "argv", ["erdify", str(empty_models_dir)]):
            result = main()

        assert result == 0  # Not an error, just a warning
        captured = capsys.readouterr()
        assert "No SQLModel tables found" in captured.err


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
