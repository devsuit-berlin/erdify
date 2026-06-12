"""Tests for generator module."""

from pathlib import Path

from erdify.generator import PlantUMLGenerator, generate_plantuml
from erdify.parser import parse_models_directory
from erdify.config import EntityInfo, FieldInfo


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


class TestRelationshipRendering:
    """Tests for drawing relationships from entity.relationships (keyless sources)."""

    def _rel_lines(self, output: str) -> list[str]:
        """Return only the relationship/arrow lines from the output."""
        return [line for line in output.splitlines() if "--" in line and ":" in line]

    def test_pydantic_relationship_is_drawn(self, pydantic_models_dir: Path):
        """Nested-ref relationships (no FK) still produce a relationship line."""
        entities, enums = parse_models_directory(pydantic_models_dir)
        output = generate_plantuml(entities, enums)

        rel_lines = self._rel_lines(output)
        customer_invoice = [line for line in rel_lines if "Customer" in line and "Invoice" in line]
        assert customer_invoice, "expected a Customer<->Invoice relationship line"

    def test_pydantic_relationship_not_duplicated(self, pydantic_models_dir: Path):
        """A bidirectional nested ref yields exactly one line per entity pair."""
        entities, enums = parse_models_directory(pydantic_models_dir)
        output = generate_plantuml(entities, enums)

        rel_lines = self._rel_lines(output)
        customer_invoice = [line for line in rel_lines if "Customer" in line and "Invoice" in line]
        assert len(customer_invoice) == 1

    def test_sqlmodel_relationship_not_doubled_by_relationship_list(self, sample_models_dir: Path):
        """SQLModel FK line must not be duplicated by the relationship-list rendering."""
        entities, enums = parse_models_directory(sample_models_dir)
        output = generate_plantuml(entities, enums)

        rel_lines = self._rel_lines(output)
        order_user = [line for line in rel_lines if "Order " in line and " User" in line]
        # Exactly the single FK-derived line: Order }o--|| User : "user_id"
        assert len(order_user) == 1

    def test_dataclass_relationship_is_drawn(self, dataclass_models_dir: Path):
        """Dataclass nested refs produce a relationship line."""
        entities, enums = parse_models_directory(dataclass_models_dir)
        output = generate_plantuml(entities, enums)

        rel_lines = self._rel_lines(output)
        warehouse_item = [line for line in rel_lines if "Warehouse" in line and "Item" in line]
        assert len(warehouse_item) == 1


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
