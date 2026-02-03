"""Tests for edge cases and error handling."""

import subprocess
import sys
from pathlib import Path


from sqlmodel_to_erd import parse_models_directory, generate_plantuml
from sqlmodel_to_erd.config import EntityInfo, FieldInfo
from sqlmodel_to_erd.generator import PlantUMLGenerator
from sqlmodel_to_erd.parser import ASTDatabaseParser


class TestMainModule:
    """Tests for __main__.py entry point."""

    def test_main_module_execution(self, sample_models_dir: Path):
        """Test running as python -m sqlmodel_to_erd."""
        result = subprocess.run(
            [sys.executable, "-m", "sqlmodel_to_erd", str(sample_models_dir)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "@startuml" in result.stdout
        assert "@enduml" in result.stdout

    def test_main_module_with_output(self, sample_models_dir: Path, temp_dir: Path):
        """Test running as module with output file."""
        output_file = temp_dir / "output.puml"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "sqlmodel_to_erd",
                str(sample_models_dir),
                "-o",
                str(output_file),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert output_file.exists()


class TestMalformedFiles:
    """Tests for handling malformed Python files."""

    def test_malformed_python_file(self, malformed_models_dir: Path, capsys):
        """Test that malformed files are handled gracefully."""
        parser = ASTDatabaseParser(malformed_models_dir)
        entities, enums = parser.parse_all_models()

        # Should not crash, but print error
        captured = capsys.readouterr()
        assert "Error parsing" in captured.err

        # Should return empty results
        assert len(entities) == 0


class TestQualifiedEnumImport:
    """Tests for enum.Enum style imports."""

    def test_parse_enum_with_qualified_import(self, edge_cases_dir: Path):
        """Test parsing enums declared as enum.Enum."""
        parser = ASTDatabaseParser(edge_cases_dir)
        entities, enums = parser.parse_all_models()

        # Should find PaymentMethod enum
        assert "PaymentMethod" in enums
        assert "CREDIT_CARD" in enums["PaymentMethod"].values
        assert "PAYPAL" in enums["PaymentMethod"].values


class TestEntityWithNoFields:
    """Tests for entities with minimal fields."""

    def test_entity_with_only_pk(self, edge_cases_dir: Path):
        """Test entity with only a primary key."""
        parser = ASTDatabaseParser(edge_cases_dir)
        entities, _ = parser.parse_all_models()

        assert "EmptyEntity" in entities
        # Should have at least the PK field
        assert len(entities["EmptyEntity"].fields) >= 1


class TestPositionalDefaults:
    """Tests for Field() with positional defaults."""

    def test_positional_string_default(self, edge_cases_dir: Path):
        """Test Field() with positional string default."""
        parser = ASTDatabaseParser(edge_cases_dir)
        entities, _ = parser.parse_all_models()

        entity = entities.get("EntityWithPositionalDefault")
        assert entity is not None

        fields = {f.name: f for f in entity.fields}
        assert "status" in fields
        assert fields["status"].default_value == "'pending'"

    def test_positional_enum_default(self, edge_cases_dir: Path):
        """Test Field() with positional enum default."""
        parser = ASTDatabaseParser(edge_cases_dir)
        entities, _ = parser.parse_all_models()

        entity = entities.get("EntityWithPositionalDefault")
        assert entity is not None

        fields = {f.name: f for f in entity.fields}
        assert "payment" in fields
        assert fields["payment"].default_value == "PaymentMethod.CREDIT_CARD"


class TestLinkTableEdgeCases:
    """Tests for link table edge cases."""

    def test_link_table_with_three_fks(self, edge_cases_dir: Path):
        """Test that link table with 3 FKs doesn't generate invalid relationships."""
        entities, enums = parse_models_directory(edge_cases_dir)
        output = generate_plantuml(entities, enums, title="Edge Cases")

        # Should not crash
        assert "@startuml" in output
        assert "@enduml" in output


class TestAutoTableName:
    """Tests for automatic table name generation."""

    def test_entity_without_tablename(self, edge_cases_dir: Path):
        """Test entity without explicit __tablename__."""
        parser = ASTDatabaseParser(edge_cases_dir)
        entities, _ = parser.parse_all_models()

        entity = entities.get("EntityWithNoTableName")
        assert entity is not None
        # Should convert CamelCase to snake_case
        assert entity.table_name == "entity_with_no_table_name"


class TestGeneratorEdgeCases:
    """Tests for generator edge cases."""

    def test_entity_with_no_fields_comment(self):
        """Test that entity with no fields shows comment."""
        entities = {
            "Empty": EntityInfo(
                name="Empty",
                table_name="empty",
                fields=[],
            )
        }
        generator = PlantUMLGenerator(entities)
        output = generator.generate()

        assert "' (no fields)" in output

    def test_link_table_with_wrong_fk_count(self):
        """Test link table with wrong number of FKs."""
        entities = {
            "BadLink": EntityInfo(
                name="BadLink",
                table_name="bad_link",
                is_link_table=True,
                fields=[
                    FieldInfo(
                        name="only_one_fk",
                        type_str="int",
                        is_foreign_key=True,
                        foreign_table="some_table.id",
                    ),
                ],
            )
        }
        generator = PlantUMLGenerator(entities)
        output = generator.generate()

        # Should not crash, just skip link table relationships
        assert "@startuml" in output
        assert "@enduml" in output

    def test_field_default_without_dot(self):
        """Test field with default value without dot (non-enum)."""
        entities = {
            "Test": EntityInfo(
                name="Test",
                table_name="test",
                fields=[
                    FieldInfo(
                        name="count",
                        type_str="int",
                        default_value="0",
                    ),
                ],
            )
        }
        generator = PlantUMLGenerator(entities)
        output = generator.generate()

        assert "= 0" in output

    def test_fk_to_nonexistent_table(self):
        """Test FK pointing to table not in entities."""
        entities = {
            "Orphan": EntityInfo(
                name="Orphan",
                table_name="orphan",
                fields=[
                    FieldInfo(
                        name="missing_ref",
                        type_str="int",
                        is_foreign_key=True,
                        foreign_table="nonexistent.id",
                    ),
                ],
            )
        }
        generator = PlantUMLGenerator(entities)
        output = generator.generate()

        # Should not crash
        assert "@startuml" in output


class TestParserRecursionSafety:
    """Tests for parser recursion safety."""

    def test_inheritance_cycle_protection(self, temp_dir: Path):
        """Test that circular inheritance doesn't cause infinite recursion."""
        models_dir = temp_dir / "cycle"
        models_dir.mkdir()

        # Create models with potential circular reference through visited set
        content = """
from sqlmodel import SQLModel, Field

class BaseA(SQLModel):
    field_a: str

class BaseB(BaseA):
    field_b: str

class Entity(BaseB, table=True):
    __tablename__: str = "entity"
    id: int = Field(primary_key=True)
"""
        (models_dir / "models.py").write_text(content)

        parser = ASTDatabaseParser(models_dir)
        entities, _ = parser.parse_all_models()

        # Should not hang or crash
        assert "Entity" in entities
        fields = {f.name for f in entities["Entity"].fields}
        assert "field_a" in fields
        assert "field_b" in fields
