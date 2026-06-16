"""Tests for the Mermaid erDiagram generator (#51)."""

from pathlib import Path

from erdify.generator import generate_mermaid
from erdify.parser import parse_models_directory


class TestMermaidStructure:
    def test_starts_with_erdiagram(self, sample_models_dir: Path):
        entities, enums = parse_models_directory(sample_models_dir)
        out = generate_mermaid(entities, enums)
        assert out.lstrip().startswith("erDiagram")

    def test_entity_block_and_primary_key(self, django_models_dir: Path):
        entities, enums = parse_models_directory(django_models_dir)
        out = generate_mermaid(entities, enums)
        assert "Author {" in out
        assert "int id PK" in out

    def test_foreign_key_attribute(self, django_models_dir: Path):
        entities, enums = parse_models_directory(django_models_dir)
        out = generate_mermaid(entities, enums)
        assert "int author_id FK" in out


class TestMermaidRelationships:
    def test_foreign_key_edge(self, django_models_dir: Path):
        entities, enums = parse_models_directory(django_models_dir)
        out = generate_mermaid(entities, enums)
        assert 'Post }o--|| Author : "author_id"' in out

    def test_one_to_one_edge(self, django_models_dir: Path):
        entities, enums = parse_models_directory(django_models_dir)
        out = generate_mermaid(entities, enums)
        assert 'Profile ||--|| Author : "author"' in out

    def test_many_to_many_edge(self, django_models_dir: Path):
        entities, enums = parse_models_directory(django_models_dir)
        out = generate_mermaid(entities, enums)
        assert 'Post }o--o{ Tag : "tags"' in out


class TestMermaidEnums:
    def test_enum_rendered_as_entity_block(self, django_models_dir: Path):
        entities, enums = parse_models_directory(django_models_dir)
        out = generate_mermaid(entities, enums)
        assert "Status {" in out
        assert "enum DRAFT" in out

    def test_enums_omitted_when_disabled(self, django_models_dir: Path):
        entities, enums = parse_models_directory(django_models_dir)
        out = generate_mermaid(entities, enums, include_enums=False)
        assert "enum DRAFT" not in out


class TestMermaidTypeSanitization:
    def test_complex_types_have_no_invalid_chars(self, sample_models_dir: Path):
        entities, enums = parse_models_directory(sample_models_dir)
        out = generate_mermaid(entities, enums)
        # No raw spaces/brackets/pipes inside attribute type tokens.
        for line in out.splitlines():
            stripped = line.strip()
            # Attribute lines look like "<type> <name> [keys]"; types must be a
            # single token. Brackets/pipes from list[str]/unions must be gone.
            if stripped and stripped[0].islower() and " " in stripped and "--" not in stripped:
                type_token = stripped.split()[0]
                assert "[" not in type_token and "]" not in type_token and "|" not in type_token
