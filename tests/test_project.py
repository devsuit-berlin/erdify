"""Resolve settings and parse a project like the CLI: load_project (#360)."""

import importlib.util
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from erdify import (
    ConfigError,
    generate_json,
    load_project,
    resolve_settings,
)
from erdify.cli import FORMATS, main
from erdify.project import FORMAT_NAMES

ROOT = Path(__file__).resolve().parent.parent

MODELS = """
from sqlmodel import SQLModel, Field


class User(SQLModel, table=True):
    id: int = Field(primary_key=True)


class AuditLog(SQLModel, table=True):
    id: int = Field(primary_key=True)
"""


def _project(tmp_path: Path, toml: str | None = None, models: str = MODELS) -> Path:
    if toml is not None:
        (tmp_path / "pyproject.toml").write_text(toml, encoding="utf-8")
    (tmp_path / "models.py").write_text(models, encoding="utf-8")
    return tmp_path


def _render_outputs() -> Any:
    spec = importlib.util.spec_from_file_location(
        "render_outputs", ROOT / "scripts" / "render_outputs.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look the module up
    spec.loader.exec_module(module)
    return module


SOURCES = list(_render_outputs().sources())


@pytest.mark.parametrize("source", SOURCES, ids=[s.id for s in SOURCES])
def test_same_model_set_as_the_cli(source: Any, capsys: pytest.CaptureFixture[str]) -> None:
    """Every fixture, catalog module and docs example: load_project == what erdify draws."""
    argv = [str(source.path), "--format", "json", "--no-default-excludes"]
    overrides: dict[str, Any] = {"format": "json", "no_default_excludes": True}
    if source.include_patterns:
        argv += ["--include", *source.include_patterns]
        overrides["include"] = source.include_patterns
    if source.sql_dialect:
        argv += ["--sql-dialect", source.sql_dialect]
        overrides["sql_dialect"] = source.sql_dialect
    if source.base_classes:
        argv += ["--base-classes", *source.base_classes]
        overrides["base_classes"] = source.base_classes
    with patch.object(sys, "argv", ["erdify", *argv]):
        assert main() == 0
    drawn = capsys.readouterr().out

    project = load_project(source.path, **overrides)

    title = project.settings.title
    assert generate_json(project.entities, project.enums, title=title) + "\n" == drawn


class TestPrecedence:
    def test_override_beats_config_beats_default(self, tmp_path: Path) -> None:
        p = _project(tmp_path, '[tool.erdify]\ntitle = "Cfg"\nexclude = ["AuditLog"]\n')

        assert resolve_settings(p).title == "Cfg"
        assert resolve_settings(p, title="Mine").title == "Mine"
        assert resolve_settings(p, title=None).title == "Cfg"  # None: not given
        assert set(load_project(p).entities) == {"User"}
        assert set(load_project(p, exclude=["User"]).entities) == {"AuditLog"}

    def test_flags_merge_by_or(self, tmp_path: Path) -> None:
        p = _project(tmp_path, "[tool.erdify]\ninfer_keys = true\n")

        assert resolve_settings(p).infer_keys is True
        assert resolve_settings(p, infer_keys=False).infer_keys is True  # can't turn off
        assert resolve_settings(p, strict=True).strict is True
        assert resolve_settings(p).strict is False

    def test_config_paths_resolve_from_the_pyproject_folder(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        p = _project(tmp_path, '[tool.erdify]\noutput = "docs/erd"\ninject = "README.md"\n')
        sub = tmp_path / "sub"
        sub.mkdir()
        monkeypatch.chdir(sub)

        settings = resolve_settings(p)

        assert settings.output == tmp_path / "docs" / "erd"
        assert settings.inject == tmp_path / "README.md"
        # An override is taken as given (the CLI's is relative to the cwd).
        assert resolve_settings(p, output=Path("x")).output == Path("x")

    def test_names_the_pyproject_it_read(self, tmp_path: Path) -> None:
        p = _project(tmp_path, "[tool.erdify]\n")
        models = p / "app" / "models.py"
        models.parent.mkdir()
        models.write_text(MODELS, encoding="utf-8")

        assert resolve_settings(models).pyproject == tmp_path / "pyproject.toml"

    def test_no_pyproject(self, tmp_path: Path) -> None:
        # tmp_path may sit below a pyproject.toml: simulate none being found.
        with patch("erdify.project.load_config", return_value=({}, None)):
            settings = resolve_settings(_project(tmp_path))

        assert settings.pyproject is None
        assert settings.title == "Database ERD"

    def test_include_default(self, tmp_path: Path) -> None:
        p = _project(tmp_path, "[tool.erdify]\n")

        assert resolve_settings(p).include == ["models.py"]
        assert resolve_settings(p).include_is_default is True
        assert resolve_settings(p, include=["*.py"]).include_is_default is False


class TestFormats:
    def test_default_format_follows_inject(self, tmp_path: Path) -> None:
        p = _project(tmp_path, "[tool.erdify]\n")

        assert resolve_settings(p).formats == ["plantuml"]
        assert resolve_settings(p, inject=Path("README.md")).formats == ["mermaid"]

    def test_string_and_unknown_formats(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        p = _project(tmp_path, '[tool.erdify]\nformat = "json"\n')

        assert resolve_settings(p).formats == ["json"]
        assert resolve_settings(p, format=["svg"]).formats == ["plantuml"]
        assert "unknown format 'svg'" in capsys.readouterr().err

    def test_format_names_match_the_cli(self) -> None:
        assert list(FORMAT_NAMES) == list(FORMATS)


class TestErrors:
    def test_missing_input(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_project(tmp_path / "nope")

    def test_unknown_override(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="unknown setting"):
            resolve_settings(_project(tmp_path), titel="typo")

    def test_invalid_config_value(self, tmp_path: Path) -> None:
        p = _project(tmp_path, "[tool.erdify]\ntitle = 42\n")

        with pytest.raises(ConfigError, match="'title' must be a string"):
            load_project(p)

    def test_cli_message_and_exit_code_unchanged(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        p = _project(tmp_path, "[tool.erdify]\ntitle = 42\n")

        with patch.object(sys, "argv", ["erdify", str(p)]):
            assert main() == 1
        err = capsys.readouterr().err
        assert err == (
            f"Error: [tool.erdify] 'title' must be a string in {tmp_path / 'pyproject.toml'}\n"
        )
