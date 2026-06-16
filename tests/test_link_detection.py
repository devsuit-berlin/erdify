"""Tests for structural link-table detection (#35).

A join table is recognized by structure - exactly two columns, both foreign
keys and both part of the primary key - regardless of its class name. The
'*Link*' name heuristic must no longer drive the decision.
"""

from pathlib import Path

from erdify.generator import PlantUMLGenerator
from erdify.parser import parse_models_directory


class TestStructuralJoinTable:
    """An association table not named *Link* is still detected as a link table."""

    def test_non_link_named_join_table_flagged(self, link_detection_dir: Path):
        entities, _ = parse_models_directory(link_detection_dir)

        assert entities["PostTag"].is_link_table is True

    def test_non_link_named_join_table_renders_m2m_path(self, link_detection_dir: Path):
        entities, enums = parse_models_directory(link_detection_dir)
        output = PlantUMLGenerator(entities, enums).generate()

        assert 'Post ||--o{ PostTag : "post_id"' in output
        assert 'PostTag }o--|| Tag : "tag_id"' in output

    def test_non_link_named_join_table_rendered_as_link_entity(self, link_detection_dir: Path):
        entities, enums = parse_models_directory(link_detection_dir)
        output = PlantUMLGenerator(entities, enums).generate()

        assert 'entity "post_tag" as PostTag << (L, #AAFFAA) link >>' in output


class TestLinkNamedNonJoinEntity:
    """An entity with 'Link' in its name but a normal structure is not a join table."""

    def test_link_named_entity_not_flagged(self, link_detection_dir: Path):
        entities, _ = parse_models_directory(link_detection_dir)

        assert entities["LinkPreview"].is_link_table is False

    def test_link_named_entity_rendered_as_plain_entity(self, link_detection_dir: Path):
        entities, enums = parse_models_directory(link_detection_dir)
        output = PlantUMLGenerator(entities, enums).generate()

        assert 'entity "link_preview" as LinkPreview {' in output
