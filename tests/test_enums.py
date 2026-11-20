"""The public enum model: which enums erdify draws, and by which entities (#369)."""

import re
from pathlib import Path
from typing import Any

import pytest

from erdify import (
    EntityInfo,
    EnumInfo,
    FieldInfo,
    enum_users,
    generate_mermaid,
    generate_plantuml,
    load_project,
    parse_models_directory,
)
from tests.render_outputs_loader import render_outputs

SOURCES = list(render_outputs().sources())


def _entity(name: str, *types: str) -> EntityInfo:
    return EntityInfo(
        name=name,
        table_name=name.lower(),
        fields=[FieldInfo(name=f"f{i}", type_str=t) for i, t in enumerate(types)],
    )


ENUMS = {
    "Status": EnumInfo("Status", ["DRAFT", "DONE"]),
    "Mood": EnumInfo("Mood", ["HAPPY"]),
    "Unused": EnumInfo("Unused", ["X"]),
}


class TestEnumUsers:
    def test_used_enums_with_their_entities(self) -> None:
        entities = {
            "Order": _entity("Order", "int", "Status", "Status"),
            "Invoice": _entity("Invoice", "models.Status", "Mood"),
            "Note": _entity("Note", "str"),
        }

        assert enum_users(entities, ENUMS) == {
            "Mood": ["Invoice"],
            "Status": ["Order", "Invoice"],
        }

    def test_no_enums(self) -> None:
        entities = {"Order": _entity("Order", "Status")}

        assert enum_users(entities, ENUMS, include_enums=False) == {}
        assert enum_users(entities, None) == {}
        assert enum_users(entities, {}) == {}

    def test_entity_names_not_dict_keys(self) -> None:
        entities = {"key": _entity("Order", "Status")}

        assert enum_users(entities, ENUMS) == {"Status": ["Order"]}

    def test_project_with_no_enums_setting(self, tmp_path: Path) -> None:
        (tmp_path / "models.py").write_text(
            "import enum\n"
            "from sqlmodel import Field, SQLModel\n\n\n"
            "class Status(str, enum.Enum):\n    DRAFT = 'draft'\n\n\n"
            "class Unused(str, enum.Enum):\n    X = 'x'\n\n\n"
            "class Order(SQLModel, table=True):\n"
            "    id: int = Field(primary_key=True)\n"
            "    status: Status\n",
            encoding="utf-8",
        )

        project = load_project(tmp_path)
        assert enum_users(project.entities, project.enums) == {"Status": ["Order"]}
        off = load_project(tmp_path, no_enums=True)
        assert enum_users(off.entities, off.enums, include_enums=not off.settings.no_enums) == {}


def _drawn_enums(source: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    entities, enums = parse_models_directory(
        source.path,
        include_patterns=source.include_patterns,
        sql_dialect=source.sql_dialect,
        base_classes=source.base_classes,
        use_default_excludes=False,
    )
    return entities, enums


@pytest.mark.parametrize("source", SOURCES, ids=[s.id for s in SOURCES])
def test_the_diagrams_draw_exactly_these_enums(source: Any) -> None:
    """One rule: every fixture's PlantUML and Mermaid enums are enum_users' keys."""
    if source.path.suffix == ".sql" or any(source.path.glob("*.sql")):
        pytest.importorskip("sqlglot")
    entities, enums = _drawn_enums(source)
    expected = [enums[key].name for key in enum_users(entities, enums)]

    plantuml = generate_plantuml(entities, enums)
    drawn = re.findall(r'^enum (?:"([^"]+)" as \S+|(\S+)) <<', plantuml, flags=re.M)
    assert [quoted or bare for quoted, bare in drawn] == expected

    mermaid = generate_mermaid(entities, enums)
    for name in expected:
        assert re.search(rf"^    \"?{re.escape(name)}\"? {{\n        enum ", mermaid, re.M)
