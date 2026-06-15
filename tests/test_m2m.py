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


class TestRegularRelationshipsStillDrawn:
    """The fix must not suppress ordinary (non-link-table) relationships."""

    def test_one_to_many_relationship_preserved(self, sample_models_dir: Path):
        entities, enums = parse_models_directory(sample_models_dir)
        output = PlantUMLGenerator(entities, enums).generate()

        # User<->Order is a plain FK relationship and must remain connected.
        assert frozenset(("User", "Order")) in _edges(output)
