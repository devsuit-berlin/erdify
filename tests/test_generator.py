"""Tests for generator module."""

from pathlib import Path

from sqlmodel_to_erd.generator import PlantUMLGenerator, generate_plantuml
from sqlmodel_to_erd.parser import parse_models_directory
from sqlmodel_to_erd.config import EntityInfo, FieldInfo


class TestPlantUMLGenerator:
    """Tests for PlantUMLGenerator class."""

    def test_generate_basic_diagram(self, sample_models_dir: Path):
        """Test generating a basic diagram."""
        entities, enums = parse_models_directory(sample_models_dir)
        generator = PlantUMLGenerator(entities, enums)
        output = generator.generate()

        # Check structure
        assert "@startuml" in output
        assert "@enduml" in output

    def test_generate_with_custom_title(self, sample_models_dir: Path):
        """Test generating a diagram with custom title."""
        entities, enums = parse_models_directory(sample_models_dir)
        generator = PlantUMLGenerator(entities, enums, title="My Custom ERD")
        output = generator.generate()

        assert "@startuml My Custom ERD" in output

    def test_generate_entities(self, sample_models_dir: Path):
        """Test that entities are included in output."""
        entities, enums = parse_models_directory(sample_models_dir)
        generator = PlantUMLGenerator(entities, enums)
        output = generator.generate()

        # Check entities are present
        assert 'entity "user" as User' in output
        assert 'entity "product" as Product' in output
        assert 'entity "order" as Order' in output

    def test_generate_enums(self, sample_models_dir: Path):
        """Test that enums are included in output."""
        entities, enums = parse_models_directory(sample_models_dir)
        generator = PlantUMLGenerator(entities, enums)
        output = generator.generate()

        # Check enums section
        assert "' Enums" in output

    def test_generate_relationships(self, sample_models_dir: Path):
        """Test that relationships are included in output."""
        entities, enums = parse_models_directory(sample_models_dir)
        generator = PlantUMLGenerator(entities, enums)
        output = generator.generate()

        # Check relationships section
        assert "' Relationships" in output
        # Order has FK to User
        assert "Order" in output and "User" in output

    def test_generate_link_table_styling(self, sample_models_dir: Path):
        """Test that link tables have special styling."""
        entities, enums = parse_models_directory(sample_models_dir)
        generator = PlantUMLGenerator(entities, enums)
        output = generator.generate()

        # Link tables should have special marker
        assert "link >>" in output

    def test_generate_primary_key_formatting(self):
        """Test primary key field formatting."""
        entities = {
            "User": EntityInfo(
                name="User",
                table_name="user",
                fields=[
                    FieldInfo(name="id", type_str="int", is_primary_key=True),
                ],
            )
        }
        generator = PlantUMLGenerator(entities)
        output = generator.generate()

        assert "primary_key(id)" in output

    def test_generate_foreign_key_formatting(self):
        """Test foreign key field formatting."""
        entities = {
            "Order": EntityInfo(
                name="Order",
                table_name="order",
                fields=[
                    FieldInfo(
                        name="user_id",
                        type_str="int",
                        is_foreign_key=True,
                        foreign_table="user.id",
                    ),
                ],
            )
        }
        generator = PlantUMLGenerator(entities)
        output = generator.generate()

        assert "foreign_key(user_id)" in output

    def test_generate_nullable_field_marker(self):
        """Test nullable fields have ? marker."""
        entities = {
            "Product": EntityInfo(
                name="Product",
                table_name="product",
                fields=[
                    FieldInfo(name="description", type_str="str", is_nullable=True),
                ],
            )
        }
        generator = PlantUMLGenerator(entities)
        output = generator.generate()

        assert "str?" in output

    def test_generate_default_value(self):
        """Test fields with default values."""
        entities = {
            "User": EntityInfo(
                name="User",
                table_name="user",
                fields=[
                    FieldInfo(name="is_active", type_str="bool", default_value="True"),
                ],
            )
        }
        generator = PlantUMLGenerator(entities)
        output = generator.generate()

        assert "= True" in output


class TestGeneratePlantuml:
    """Tests for generate_plantuml convenience function."""

    def test_generate_plantuml_basic(self, sample_models_dir: Path):
        """Test the convenience function."""
        entities, enums = parse_models_directory(sample_models_dir)
        output = generate_plantuml(entities, enums)

        assert "@startuml" in output
        assert "@enduml" in output

    def test_generate_plantuml_custom_title(self, sample_models_dir: Path):
        """Test with custom title."""
        entities, enums = parse_models_directory(sample_models_dir)
        output = generate_plantuml(entities, enums, title="Test ERD")

        assert "@startuml Test ERD" in output

    def test_generate_plantuml_no_enums(self, sample_models_dir: Path):
        """Test with enums disabled."""
        entities, enums = parse_models_directory(sample_models_dir)
        output = generate_plantuml(entities, enums, include_enums=False)

        # Should not have enum definitions
        # Note: the "' Enums" comment may still be there but no enum blocks
        assert "enum UserRole" not in output

    def test_generate_plantuml_empty_entities(self):
        """Test with no entities."""
        output = generate_plantuml({}, {})

        assert "@startuml" in output
        assert "@enduml" in output
        assert "' Entities" in output
