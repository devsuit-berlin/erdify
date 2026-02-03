"""Integration tests comparing generated output against expected .puml files."""

import pytest
from pathlib import Path

from sqlmodel_to_erd import parse_models_directory, generate_plantuml


FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestGoldenFiles:
    """Tests that compare generated output against expected .puml files."""

    @pytest.mark.parametrize(
        "fixture_name,title",
        [
            ("ecommerce", "E-Commerce ERD"),
            ("inheritance", "Inheritance ERD"),
        ],
    )
    def test_generated_matches_expected(self, fixture_name: str, title: str):
        """Test that generated PlantUML matches the expected golden file."""
        fixture_dir = FIXTURES_DIR / fixture_name
        expected_file = fixture_dir / "expected.puml"

        # Parse models and generate output
        entities, enums = parse_models_directory(fixture_dir)
        generated = generate_plantuml(entities, enums, title=title)

        # Load expected output
        expected = expected_file.read_text().rstrip("\n")

        # Compare (strip trailing newlines for consistency)
        assert generated == expected, (
            f"Generated output does not match {expected_file}.\n"
            f"To update the expected file, run:\n"
            f"  sqlmodel-erd {fixture_dir} --title '{title}' -o {expected_file}"
        )

    def test_ecommerce_entity_count(self):
        """Test that e-commerce fixture has expected number of entities."""
        entities, enums = parse_models_directory(FIXTURES_DIR / "ecommerce")

        assert len(entities) == 5  # User, Product, Order, OrderItem, UserProductLink
        assert len(enums) == 2  # UserRole, OrderStatus

    def test_inheritance_entity_count(self):
        """Test that inheritance fixture has expected number of entities."""
        entities, enums = parse_models_directory(FIXTURES_DIR / "inheritance")

        assert len(entities) == 2  # Article, Comment
        assert len(enums) == 0

    def test_ecommerce_relationships(self):
        """Test that e-commerce fixture has correct relationships."""
        entities, _ = parse_models_directory(FIXTURES_DIR / "ecommerce")

        # Order -> User (via user_id FK)
        order_fks = [f for f in entities["Order"].fields if f.is_foreign_key]
        assert len(order_fks) == 1
        assert order_fks[0].foreign_table == "user.id"

        # OrderItem -> Order, Product (via FKs)
        item_fks = [f for f in entities["OrderItem"].fields if f.is_foreign_key]
        assert len(item_fks) == 2
        fk_tables = {f.foreign_table for f in item_fks}
        assert fk_tables == {"order.id", "product.id"}

        # UserProductLink is a link table
        assert entities["UserProductLink"].is_link_table is True

    def test_inheritance_inherited_fields(self):
        """Test that inherited fields are correctly resolved."""
        entities, _ = parse_models_directory(FIXTURES_DIR / "inheritance")

        article_fields = {f.name for f in entities["Article"].fields}

        # Should have own fields
        assert "title" in article_fields
        assert "content" in article_fields
        assert "published" in article_fields

        # Should have inherited fields from BaseEntity and TimestampMixin
        assert "id" in article_fields
        assert "created_at" in article_fields
        assert "updated_at" in article_fields


class TestGoldenFileHelpers:
    """Helper tests for golden file management."""

    def test_all_fixtures_have_expected_files(self):
        """Ensure all model fixtures have corresponding expected.puml files."""
        for fixture_dir in FIXTURES_DIR.iterdir():
            if not fixture_dir.is_dir():
                continue
            if fixture_dir.name == "__pycache__":
                continue

            models_file = fixture_dir / "models.py"
            expected_file = fixture_dir / "expected.puml"

            if models_file.exists():
                # Empty fixtures don't need expected files
                content = models_file.read_text()
                has_tables = "table=True" in content

                if has_tables:
                    assert expected_file.exists(), (
                        f"Missing expected.puml for {fixture_dir.name}. "
                        f"Generate with: sqlmodel-erd {fixture_dir} -o {expected_file}"
                    )
