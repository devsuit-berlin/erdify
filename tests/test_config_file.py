"""Tests for [tool.erdify] pyproject config (#49) and --check mode (#50)."""

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from erdify.cli import main
from erdify.pyproject import load_config

MODELS = """
from sqlmodel import SQLModel, Field


class User(SQLModel, table=True):
    __tablename__: str = "user"
    id: int = Field(primary_key=True)


class AuditLog(SQLModel, table=True):
    __tablename__: str = "audit_log"
    id: int = Field(primary_key=True)
"""


def _project(tmp_path: Path, toml: str) -> Path:
    (tmp_path / "pyproject.toml").write_text(toml)
    (tmp_path / "models.py").write_text(MODELS)
    return tmp_path


class TestLoadConfig:
    def test_returns_tool_erdify_table(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").write_text('[tool.erdify]\ntitle = "X"\n')
        config, base = load_config(tmp_path)
        assert config == {"title": "X"}
        assert base == tmp_path

    def test_empty_when_no_pyproject(self, tmp_path: Path):
        assert load_config(tmp_path) == ({}, None)

    def test_walks_up_from_subdir(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").write_text('[tool.erdify]\ntitle = "X"\n')
        sub = tmp_path / "a" / "b"
        sub.mkdir(parents=True)
        config, base = load_config(sub)
        assert config == {"title": "X"}
        assert base == tmp_path

    def test_unknown_keys_dropped(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").write_text('[tool.erdify]\ntitle = "X"\nbogus = 1\n')
        config, _ = load_config(tmp_path)
        assert config == {"title": "X"}


class TestConfigApplied:
    def test_title_from_config(self, tmp_path: Path, capsys):
        p = _project(tmp_path, '[tool.erdify]\ntitle = "Cfg Title"\n')
        with patch.object(sys, "argv", ["erdify", str(p)]):
            assert main() == 0
        assert "@startuml Cfg Title" in capsys.readouterr().out

    def test_exclude_from_config(self, tmp_path: Path, capsys):
        p = _project(tmp_path, '[tool.erdify]\nexclude = ["audit_log"]\n')
        with patch.object(sys, "argv", ["erdify", str(p)]):
            assert main() == 0
        out = capsys.readouterr().out
        assert "as AuditLog" not in out
        assert "as User" in out

    def test_cli_overrides_config_title(self, tmp_path: Path, capsys):
        p = _project(tmp_path, '[tool.erdify]\ntitle = "Cfg"\n')
        with patch.object(sys, "argv", ["erdify", str(p), "--title", "CLI"]):
            assert main() == 0
        assert "@startuml CLI" in capsys.readouterr().out

    def test_config_output_relative_to_project(self, tmp_path: Path):
        p = _project(tmp_path, '[tool.erdify]\noutput = "out/erd.puml"\n')
        with patch.object(sys, "argv", ["erdify", str(p)]):
            assert main() == 0
        assert (tmp_path / "out" / "erd.puml").exists()


class TestCheckMode:
    def test_check_up_to_date_exits_zero(self, tmp_path: Path):
        p = _project(tmp_path, "")
        out = tmp_path / "erd.puml"
        with patch.object(sys, "argv", ["erdify", str(p), "-o", str(out)]):
            assert main() == 0
        with patch.object(sys, "argv", ["erdify", str(p), "-o", str(out), "--check"]):
            assert main() == 0

    def test_check_stale_exits_one_without_writing(self, tmp_path: Path):
        p = _project(tmp_path, "")
        out = tmp_path / "erd.puml"
        out.write_text("stale")
        with patch.object(sys, "argv", ["erdify", str(p), "-o", str(out), "--check"]):
            assert main() == 1
        assert out.read_text() == "stale"  # not overwritten

    def test_check_missing_output_exits_one(self, tmp_path: Path):
        p = _project(tmp_path, "")
        out = tmp_path / "missing.puml"
        with patch.object(sys, "argv", ["erdify", str(p), "-o", str(out), "--check"]):
            assert main() == 1

    def test_check_requires_output(self, tmp_path: Path, capsys):
        p = _project(tmp_path, "")
        with patch.object(sys, "argv", ["erdify", str(p), "--check"]):
            assert main() != 0
        assert "--output" in capsys.readouterr().err

    def test_check_all_formats(self, tmp_path: Path):
        p = _project(tmp_path, "")
        base = tmp_path / "erd"
        with patch.object(
            sys, "argv", ["erdify", str(p), "-o", str(base), "--format", "plantuml", "mermaid"]
        ):
            assert main() == 0
        # both up to date -> 0
        with patch.object(
            sys,
            "argv",
            ["erdify", str(p), "-o", str(base), "--format", "plantuml", "mermaid", "--check"],
        ):
            assert main() == 0
        # break only the mermaid file -> non-zero
        (tmp_path / "erd.mmd").write_text("stale")
        with patch.object(
            sys,
            "argv",
            ["erdify", str(p), "-o", str(base), "--format", "plantuml", "mermaid", "--check"],
        ):
            assert main() == 1

    def test_module_entrypoint_propagates_exit_code(self, tmp_path: Path):
        """`python -m erdify ... --check` must exit non-zero when stale (CI relies on it)."""
        p = _project(tmp_path, "")
        out = tmp_path / "erd.puml"
        out.write_text("stale")
        result = subprocess.run(
            [sys.executable, "-m", "erdify", str(p), "-o", str(out), "--check"],
            capture_output=True,
        )
        assert result.returncode == 1


def test_sql_dialect_config_key_recognized(tmp_path):
    from erdify.pyproject import load_config

    (tmp_path / "pyproject.toml").write_text('[tool.erdify]\nsql_dialect = "postgres"\n')
    config, _ = load_config(tmp_path)
    assert config.get("sql_dialect") == "postgres"


def test_sql_dialect_non_string_rejected(tmp_path):
    """sql_dialect = 42 must be rejected with a non-zero exit."""
    from erdify.pyproject import load_config

    (tmp_path / "pyproject.toml").write_text("[tool.erdify]\nsql_dialect = 42\n")
    with pytest.raises(SystemExit):
        load_config(tmp_path)
