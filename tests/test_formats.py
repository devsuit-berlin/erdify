"""Tests for the JSON (#63) and HTML (#59) output formats."""

import json
from pathlib import Path

from erdify.generator import generate_html, generate_json
from erdify.parser import parse_models_directory


class TestJsonFormat:
    def test_valid_json_with_entities(self, sample_models_dir: Path):
        entities, enums = parse_models_directory(sample_models_dir)
        data = json.loads(generate_json(entities, enums, title="My ERD"))

        assert data["title"] == "My ERD"
        names = {e["name"] for e in data["entities"]}
        assert "User" in names and "Order" in names

    def test_columns_expose_keys(self, django_models_dir: Path):
        entities, enums = parse_models_directory(django_models_dir)
        data = json.loads(generate_json(entities, enums))
        post = next(e for e in data["entities"] if e["name"] == "Post")
        fields = {f["name"]: f for f in post["fields"]}

        assert fields["id"]["primary_key"] is True
        assert fields["author_id"]["foreign_key"] is True
        assert fields["author_id"]["foreign_table"] == "author.id"

    def test_relationships_are_objects(self, django_models_dir: Path):
        entities, enums = parse_models_directory(django_models_dir)
        data = json.loads(generate_json(entities, enums))
        post = next(e for e in data["entities"] if e["name"] == "Post")
        m2m = [r for r in post["relationships"] if r["attribute"] == "tags"]

        assert m2m and m2m[0]["target"] == "Tag" and m2m[0]["type"] == "many_to_many"

    def test_enums_included(self, django_models_dir: Path):
        entities, enums = parse_models_directory(django_models_dir)
        data = json.loads(generate_json(entities, enums))
        enum_names = {e["name"] for e in data["enums"]}

        assert "Status" in enum_names

    def test_enums_omitted_when_disabled(self, django_models_dir: Path):
        entities, enums = parse_models_directory(django_models_dir)
        data = json.loads(generate_json(entities, enums, include_enums=False))

        assert data["enums"] == []


class TestHtmlFormat:
    def test_self_contained_mermaid_page(self, sample_models_dir: Path):
        entities, enums = parse_models_directory(sample_models_dir)
        out = generate_html(entities, enums, title="My ERD")

        assert out.lstrip().startswith("<!DOCTYPE html>")
        assert '<pre class="mermaid">' in out
        assert "erDiagram" in out

    def test_pinned_mermaid_cdn(self, sample_models_dir: Path):
        entities, enums = parse_models_directory(sample_models_dir)
        out = generate_html(entities, enums)

        assert "mermaid@11" in out  # pinned major version

    def test_title_escaped(self, sample_models_dir: Path):
        entities, enums = parse_models_directory(sample_models_dir)
        out = generate_html(entities, enums, title="A & B <x>")

        assert "A &amp; B &lt;x&gt;" in out
        assert "<x>" not in out.replace("&lt;x&gt;", "")
