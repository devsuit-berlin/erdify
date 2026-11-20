"""Resolve settings and parse a project like the CLI: load_project (#360)."""

import inspect
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from erdify import ConfigError, generate_json, load_project, resolve_settings
from erdify.cli import FORMATS, _overrides, build_parser, main
from erdify.project import FORMAT_NAMES, _resolve
from erdify.pyproject import CONFIG_KEYS
from tests.render_outputs_loader import render_outputs

MODELS = """
from sqlmodel import SQLModel, Field


class User(SQLModel, table=True):
    id: int = Field(primary_key=True)


class AuditLog(SQLModel, table=True):
    id: int = Field(primary_key=True)
"""


def _project(tmp_path: Path, toml: str | None = None, models: str = MODELS) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    if toml is not None:
        (tmp_path / "pyproject.toml").write_text(toml, encoding="utf-8")
    (tmp_path / "models.py").write_text(models, encoding="utf-8")
    return tmp_path


def _cli_json(argv: list[str], capsys: pytest.CaptureFixture[str]) -> str:
    with patch.object(sys, "argv", ["erdify", *argv]):
        assert main() == 0
    return capsys.readouterr().out


def _project_json(path: Path, **overrides: Any) -> str:
    project = load_project(path, **overrides)
    title = project.settings.title
    return generate_json(project.entities, project.enums, title=title) + "\n"


SOURCES = list(render_outputs().sources())


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
    if source.exclude_paths:
        argv += ["--exclude-paths", *source.exclude_paths]
        overrides["exclude_paths"] = source.exclude_paths

    assert _project_json(source.path, **overrides) == _cli_json(argv, capsys)


def test_same_model_set_as_the_cli_with_a_config_table(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The settings resolution itself: a [tool.erdify] table, plus CLI flags on top."""
    p = _project(
        tmp_path,
        "[tool.erdify]\n"
        'title = "Shop"\n'
        'format = "json"\n'
        'include = ["models.py", "extra/*.py"]\n'
        'exclude = ["AuditLog"]\n'
        'sources = ["sqlmodel", "pydantic"]\n'
        "infer_keys = true\n",
    )
    (tmp_path / "extra").mkdir()
    (tmp_path / "extra" / "dto.py").write_text(
        "from pydantic import BaseModel\n\n"
        "class Order(BaseModel):\n    id: int\n    user_id: int\n",
        encoding="utf-8",
    )

    plain = _cli_json([str(p)], capsys)
    assert _project_json(p) == plain
    assert '"title": "Shop"' in plain and '"Order"' in plain and '"AuditLog"' not in plain

    flagged = _cli_json([str(p), "--exclude", "Order", "--django-raw-types"], capsys)
    assert _project_json(p, exclude=["Order"], django_raw_types=True) == flagged


class TestPrecedence:
    def test_override_beats_config_beats_default(self, tmp_path: Path) -> None:
        p = _project(tmp_path, '[tool.erdify]\ntitle = "Cfg"\nexclude = ["AuditLog"]\n')

        assert resolve_settings(p).title == "Cfg"
        assert resolve_settings(p, title="Mine").title == "Mine"
        assert resolve_settings(p, title=None).title == "Cfg"  # None: not given
        assert set(load_project(p).entities) == {"User"}
        assert set(load_project(p, exclude=["User"]).entities) == {"AuditLog"}
        assert set(load_project(p, exclude=[]).entities) == {"User", "AuditLog"}

    def test_flags_are_three_state(self, tmp_path: Path) -> None:
        p = _project(tmp_path, "[tool.erdify]\nstrict = true\n")

        assert resolve_settings(p).strict is True  # None: the config's value
        assert resolve_settings(p, strict=False).strict is False  # turned off
        assert resolve_settings(p, infer_keys=True).infer_keys is True
        assert resolve_settings(p).infer_keys is False  # the default

    def test_cli_flags_still_merge_by_or(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        p = _project(
            tmp_path,
            '[tool.erdify]\nno_relationships = true\nformat = "json"\n',
            models="from pydantic import BaseModel\n\n"
            "class User(BaseModel):\n    best_friend: 'User | None'\n",
        )

        # An omitted CLI flag leaves the config's value on.
        assert '"relationships": []' in _cli_json([str(p)], capsys)
        # Control: the model has a relationship, which the flag alone removes.
        (p / "pyproject.toml").write_text(
            '[tool.erdify]\nno_relationships = false\nformat = "json"\n', encoding="utf-8"
        )
        assert '"relationships": []' not in _cli_json([str(p)], capsys)
        assert '"relationships": []' in _cli_json([str(p), "--no-relationships"], capsys)

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
        assert resolve_settings(p, inject="y.md").inject == Path("y.md")

    def test_names_the_pyproject(self, tmp_path: Path) -> None:
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
        p = _project(tmp_path / "plain", "[tool.erdify]\n")

        assert resolve_settings(p).include == ("models.py",)
        assert _resolve(p, {})[1] is True  # the CLI's models/ package hint
        assert _resolve(p, {"include": ["*.py"]})[1] is False
        configured = _project(tmp_path / "set", '[tool.erdify]\ninclude = ["models.py"]\n')
        assert _resolve(configured, {})[1] is False

    def test_settings_are_hashable(self, tmp_path: Path) -> None:
        p = _project(tmp_path, '[tool.erdify]\nexclude = ["A"]\n')
        settings = resolve_settings(p)

        assert settings.exclude == ("A",)
        assert hash(settings) == hash(resolve_settings(p))


def test_config_string_for_a_list_is_a_list_of_it(tmp_path: Path) -> None:
    """Lenient config: `exclude = "AuditLog"` means ["AuditLog"] (it was read letter by letter)."""
    p = _project(tmp_path, '[tool.erdify]\nexclude = "AuditLog"\ninclude = "models.py"\n')

    settings = resolve_settings(p)

    assert (settings.exclude, settings.include) == (("AuditLog",), ("models.py",))
    assert set(load_project(p).entities) == {"User"}


def test_path_may_be_a_string(tmp_path: Path) -> None:
    p = _project(tmp_path, "[tool.erdify]\n")

    assert load_project(str(p)).settings.input == p


class TestFormats:
    def test_default_format_follows_inject(self, tmp_path: Path) -> None:
        p = _project(tmp_path, "[tool.erdify]\n")

        assert resolve_settings(p).formats == ("plantuml",)
        assert resolve_settings(p, inject=Path("README.md")).formats == ("mermaid",)

    def test_string_and_unknown_formats(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        p = _project(tmp_path, '[tool.erdify]\nformat = "json"\n')

        assert resolve_settings(p).formats == ("json",)
        assert resolve_settings(p, format="mermaid").formats == ("mermaid",)
        assert resolve_settings(p, format=["svg"]).formats == ("plantuml",)
        assert "unknown format 'svg'" in capsys.readouterr().err

    def test_format_names_match_the_cli(self) -> None:
        assert list(FORMAT_NAMES) == list(FORMATS)


def test_cli_passes_every_config_key() -> None:
    args = build_parser().parse_args(["."])

    assert set(_overrides(args)) == set(CONFIG_KEYS)
    # Omitted options and flags are "not given".
    assert set(_overrides(args).values()) == {None}


def test_keywords_are_the_config_keys() -> None:
    """A new [tool.erdify] key needs its keyword in both functions (and the CLI call)."""
    for function in (resolve_settings, load_project):
        keywords = {
            name
            for name, param in inspect.signature(function).parameters.items()
            if param.kind is inspect.Parameter.KEYWORD_ONLY
        }
        assert keywords == set(CONFIG_KEYS)


class TestErrors:
    def test_missing_input(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_project(tmp_path / "nope")

    def test_unknown_keyword(self, tmp_path: Path) -> None:
        with pytest.raises(TypeError):
            load_project(_project(tmp_path), titel="typo")  # type: ignore[call-arg]

    @pytest.mark.parametrize("key", ["include", "exclude", "sources"])
    def test_string_for_a_list_override(self, tmp_path: Path, key: str) -> None:
        with pytest.raises(ConfigError, match=f"'{key}' must be a list of strings"):
            load_project(_project(tmp_path), **{key: "models.py"})

    def test_one_shot_iterable_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="'exclude' must be a list of strings"):
            load_project(_project(tmp_path), exclude=(p for p in ["User"]))  # type: ignore[arg-type]

    def test_non_bool_flag_argument(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="'strict' must be a bool or None"):
            load_project(_project(tmp_path), strict="false")  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        ("toml", "message"),
        [
            ("title = 42", "'title' must be a string"),
            ("inject = 42", "'inject' must be a string"),
            ("include = 1", "'include' must be a list of strings"),
            ("exclude = [1]", "'exclude' must be a list of strings"),
            ("format = 42", "'format' must be a list of strings"),
            ('format = ["json", 1]', "'format' must be a list of strings"),
        ],
    )
    def test_invalid_config_value(self, tmp_path: Path, toml: str, message: str) -> None:
        p = _project(tmp_path, f"[tool.erdify]\n{toml}\n")

        with pytest.raises(ConfigError, match=message):
            load_project(p)

    def test_cli_message_and_exit_code(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        p = _project(tmp_path, "[tool.erdify]\ntitle = 42\n")

        with patch.object(sys, "argv", ["erdify", str(p)]):
            assert main() == 1
        assert capsys.readouterr().err == (
            f"Error: [tool.erdify] 'title' must be a string in {tmp_path / 'pyproject.toml'}\n"
        )
