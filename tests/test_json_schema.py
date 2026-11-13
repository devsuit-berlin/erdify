"""The JSON output matches the published schema (docs/schema/output-v1.json, #268).

Every source ``scripts/render_outputs.py`` renders (the fixtures, the edge-case
catalogs and the docs examples) is validated against the schema. The schema
allows keys it doesn't list, as consumers must ignore them, so the keys erdify
emits are also compared with the schema's exactly: a new key has to be added
to the schema and to the docs tables (also checked here) in the same change.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from erdify import JSON_SCHEMA_VERSION

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "docs" / "schema" / "output-v1.json"
DOCS = ROOT / "docs" / "usage" / "output-formats.md"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _load_render_outputs() -> Any:
    spec = importlib.util.spec_from_file_location(
        "render_outputs", ROOT / "scripts" / "render_outputs.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look the module up
    spec.loader.exec_module(module)
    return module


render_outputs = _load_render_outputs()
SOURCES = list(render_outputs.sources())


def _properties(definition: str | None = None) -> set[str]:
    node = SCHEMA if definition is None else SCHEMA["$defs"][definition]
    return set(node["properties"])


def test_schema_is_valid() -> None:
    Draft202012Validator.check_schema(SCHEMA)
    assert SCHEMA["properties"]["schema_version"]["const"] == JSON_SCHEMA_VERSION


@pytest.mark.parametrize("source", SOURCES, ids=[s.id for s in SOURCES])
def test_output_matches_the_schema(source: Any) -> None:
    document = json.loads(render_outputs.render(source)["json"])
    errors = sorted(Draft202012Validator(SCHEMA).iter_errors(document), key=str)
    assert not errors, "\n".join(f"{list(e.absolute_path)}: {e.message}" for e in errors)
    # Exactly the schema's keys: a key erdify adds must be documented.
    assert set(document) == _properties()
    for entity in document["entities"]:
        assert set(entity) == _properties("entity")
        for field in entity["fields"]:
            assert set(field) == _properties("field")
        for relationship in entity["relationships"]:
            assert set(relationship) == _properties("relationship")
    for enum in document["enums"]:
        assert set(enum) == _properties("enum")


def test_sources_cover_every_framework() -> None:
    """Guard the source list: every model source shows up in some output."""
    seen = {
        entity["source"]
        for source in SOURCES
        for entity in json.loads(render_outputs.render(source)["json"])["entities"]
    }
    assert seen == set(SCHEMA["$defs"]["entity"]["properties"]["source"]["enum"])


def _documented_keys() -> dict[str, set[str]]:
    """The keys of each table in the docs' "Schema" section, by its label."""
    text = DOCS.read_text(encoding="utf-8")
    section = text.split("### Schema", 1)[1].split("\n### ", 1)[0]
    tables: dict[str, set[str]] = {}
    label = ""
    for line in section.splitlines():
        heading = re.fullmatch(r"([A-Z][a-z ]+):", line.strip())
        if heading:
            label = heading.group(1)
            tables[label] = set()
        row = re.match(r"\| `([a-z_]+)` \|", line)
        if row and label:
            tables[label].add(row.group(1))
    return tables


def test_docs_list_the_schema_keys() -> None:
    assert _documented_keys() == {
        "Top level": _properties(),
        "Entity": _properties("entity"),
        "Field": _properties("field"),
        "Relationship": _properties("relationship"),
        "Enum": _properties("enum"),
    }


def test_schema_rejects_a_wrong_document() -> None:
    """The schema really constrains the shape (a broken one would accept anything)."""
    document = {"schema_version": 1, "title": "t", "entities": [{"name": "A"}], "enums": []}
    assert list(Draft202012Validator(SCHEMA).iter_errors(document))


def test_sql_dialects_match_the_ground_truth_tests() -> None:
    """A catalog / fixture SQL source is rendered with the dialect its ground truth uses."""
    from tests.test_ground_truth_sql import DIALECTS

    sources = {
        name: dialect
        for name, dialect in DIALECTS.items()
        # Inline snippets and the docs page's SQL block aren't rendered.
        if "::" not in name and not name.endswith(".md")
    }
    assert sources == render_outputs.SQL_DIALECTS
