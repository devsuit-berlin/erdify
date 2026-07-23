"""Tests for structural link-table detection (#35, #118).

A join table is recognized by structure - a composite primary key made up
entirely of foreign keys, with no payload columns - regardless of its class
name or how many FKs it joins. The '*Link*' name heuristic must no longer
drive the decision.
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


class TestTernaryJoinTable:
    """A composite-PK table with more than two FKs is still a link table (#118)."""

    def test_ternary_join_table_flagged(self, link_detection_dir: Path):
        entities, _ = parse_models_directory(link_detection_dir)

        assert entities["ProjectMembership"].is_link_table is True

    def test_ternary_join_table_rendered_as_link_entity(self, link_detection_dir: Path):
        entities, enums = parse_models_directory(link_detection_dir)
        output = PlantUMLGenerator(entities, enums).generate()

        assert 'entity "project_membership" as ProjectMembership << (L, #AAFFAA) link >>' in output

    def test_ternary_join_table_renders_star_of_edges(self, link_detection_dir: Path):
        entities, enums = parse_models_directory(link_detection_dir)
        output = PlantUMLGenerator(entities, enums).generate()

        assert 'Project ||--o{ ProjectMembership : "project_id"' in output
        assert 'User ||--o{ ProjectMembership : "user_id"' in output
        assert 'Role ||--o{ ProjectMembership : "role_id"' in output
