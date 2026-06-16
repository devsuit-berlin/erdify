"""Regression tests for many-to-many relationships declared via a link table.

A relationship that carries link_model= (SQLModel) or secondary= (SQLAlchemy)
is an M:N association already expressed by the link table. It must not also
produce a direct, mis-cardinalized 1:N edge between the two endpoints.
"""

from pathlib import Path

from erdify.generator import PlantUMLGenerator
from erdify.parser import parse_models_directory


def _edges(output: str) -> list[frozenset[str]]:
    """Return the endpoint pairs of every PlantUML connector line.

    A connector looks like ``Left ||--o{ Right : "label"``; this returns
    ``frozenset({"Left", "Right"})`` for each such line.
    """
    pairs: list[frozenset[str]] = []
    for line in output.splitlines():
        if "--" not in line or ":" not in line:
            continue
        tokens = line.split(":", 1)[0].split()
        if len(tokens) >= 3:
            pairs.append(frozenset((tokens[0], tokens[-1])))
    return pairs


class TestSQLModelLinkModel:
    """SQLModel Relationship(link_model=...) must not emit a direct edge."""

    def test_link_table_path_present(self, m2m_link_model_dir: Path):
        entities, enums = parse_models_directory(m2m_link_model_dir)
        output = PlantUMLGenerator(entities, enums).generate()

        # The correct M:N path goes through the link table.
        assert 'Restaurant ||--o{ RestaurantStaffLink : "restaurant_id"' in output
        assert 'RestaurantStaffLink }o--|| Staff : "staff_id"' in output

    def test_no_spurious_direct_edge(self, m2m_link_model_dir: Path):
        entities, enums = parse_models_directory(m2m_link_model_dir)
        output = PlantUMLGenerator(entities, enums).generate()

        # No direct Restaurant<->Staff connector may be drawn.
        assert frozenset(("Restaurant", "Staff")) not in _edges(output)

    def test_link_model_relationship_not_stored_as_direct(self, m2m_link_model_dir: Path):
        entities, _ = parse_models_directory(m2m_link_model_dir)

        # The link_model relationship must not survive as a direct declared edge.
        assert entities["Restaurant"].relationships == []
        assert entities["Staff"].relationships == []


class TestSQLAlchemySecondary:
    """SQLAlchemy relationship(secondary=...) must not emit a direct edge."""

    def test_link_table_path_present(self, m2m_secondary_dir: Path):
        entities, enums = parse_models_directory(m2m_secondary_dir)
        output = PlantUMLGenerator(entities, enums).generate()

        assert 'Post ||--o{ PostTagLink : "post_id"' in output
        assert 'PostTagLink }o--|| Tag : "tag_id"' in output

    def test_no_spurious_direct_edge(self, m2m_secondary_dir: Path):
        entities, enums = parse_models_directory(m2m_secondary_dir)
        output = PlantUMLGenerator(entities, enums).generate()

        assert frozenset(("Post", "Tag")) not in _edges(output)

    def test_secondary_relationship_not_stored_as_direct(self, m2m_secondary_dir: Path):
        entities, _ = parse_models_directory(m2m_secondary_dir)

        assert entities["Post"].relationships == []
        assert entities["Tag"].relationships == []


class TestSQLAlchemySecondaryCoreTable:
    """relationship(secondary=Table(...)) where the association is a Core Table.

    The module-level ``Table(...)`` must be synthesized into a link entity so the
    M:N is drawn through it - never dropped and never a direct 1:N edge (#34).
    """

    def test_core_table_modeled_as_link_entity(self, m2m_secondary_table_dir: Path):
        entities, _ = parse_models_directory(m2m_secondary_table_dir)

        assert "post_tag" in entities
        assert entities["post_tag"].is_link_table is True

    def test_link_table_path_present(self, m2m_secondary_table_dir: Path):
        entities, enums = parse_models_directory(m2m_secondary_table_dir)
        output = PlantUMLGenerator(entities, enums).generate()

        assert 'Post ||--o{ post_tag : "post_id"' in output
        assert 'post_tag }o--|| Tag : "tag_id"' in output

    def test_no_spurious_direct_edge(self, m2m_secondary_table_dir: Path):
        entities, enums = parse_models_directory(m2m_secondary_table_dir)
        output = PlantUMLGenerator(entities, enums).generate()

        assert frozenset(("Post", "Tag")) not in _edges(output)

    def test_untyped_columns_have_no_dangling_colon(self, m2m_secondary_table_dir: Path):
        entities, enums = parse_models_directory(m2m_secondary_table_dir)
        output = PlantUMLGenerator(entities, enums).generate()

        # Core Column(...) without an explicit type must not render "name : ".
        assert "primary_key(post_id)" in output
        assert "primary_key(post_id) :" not in output


class TestRegularRelationshipsStillDrawn:
    """The fix must not suppress ordinary (non-link-table) relationships."""

    def test_one_to_many_relationship_preserved(self, sample_models_dir: Path):
        entities, enums = parse_models_directory(sample_models_dir)
        output = PlantUMLGenerator(entities, enums).generate()

        # User<->Order is a plain FK relationship and must remain connected.
        assert frozenset(("User", "Order")) in _edges(output)
