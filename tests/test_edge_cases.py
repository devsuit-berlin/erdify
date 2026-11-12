"""Tests for edge cases and error handling."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest


from erdify import parse_models_directory, generate_plantuml
from erdify.config import EntityInfo, FieldInfo
from erdify.generator import PlantUMLGenerator
from erdify.parser import ASTDatabaseParser
from erdify.parser.dialects import ParseContext
from erdify.parser.dialects.keyless import PydanticDialect


class TestMainModule:
    """Tests for __main__.py entry point."""

    def test_main_module_execution(self, sample_models_dir: Path):
        """Test running as python -m erdify."""
        result = subprocess.run(
            [sys.executable, "-m", "erdify", str(sample_models_dir)],
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
                "erdify",
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
        """A SQLModel table without __tablename__ gets SQLModel's default (#291)."""
        parser = ASTDatabaseParser(edge_cases_dir)
        entities, _ = parser.parse_all_models()

        entity = entities.get("EntityWithNoTableName")
        assert entity is not None
        # SQLModel lower-cases the class name; it is not snake_case.
        assert entity.table_name == "entitywithnotablename"


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


class TestTypeStringCleanup:
    """Type-string cleanup must strip the optional wrapper without mangling
    generic args (regression: ``list[str]`` lost its closing bracket).
    """

    @pytest.mark.parametrize(
        "annotation, expected_type, expected_nullable",
        [
            ("list[str]", "list[str]", False),
            ("list[str] | None = None", "list[str]", True),
            ("Optional[list[str]] = None", "list[str]", True),
            ("dict[str, int]", "dict[str, int]", False),
            ("str | None", "str", True),
            ("Optional[str]", "str", True),
            ("str", "str", False),
        ],
    )
    def test_generic_brackets_preserved(
        self, annotation: str, expected_type: str, expected_nullable: bool
    ):
        dialect = PydanticDialect(ParseContext())

        node = ast.parse(f"x: {annotation}").body[0]
        assert isinstance(node, ast.AnnAssign)
        field = dialect._parse_field(node)

        assert field is not None
        assert field.type_str == expected_type
        assert field.is_nullable is expected_nullable


class TestEnumBases:
    """#296: every enum.Enum subclass is an enum, also through a project base."""

    def _enums(self, tmp_path: Path, src: str) -> dict[str, list[str]]:
        (tmp_path / "models.py").write_text(src)
        _, enums = parse_models_directory(tmp_path)
        return {name: enum.values for name, enum in enums.items()}

    def test_stdlib_enum_bases(self, tmp_path: Path):
        src = (
            "import enum\n"
            "from enum import IntEnum, StrEnum\n\n"
            "class A(IntEnum):\n    X = 1\n\n"
            "class B(StrEnum):\n    X = 'x'\n\n"
            "class C(enum.Flag):\n    X = 1\n\n"
            "class D(enum.IntFlag):\n    X = 1\n"
        )
        assert self._enums(tmp_path, src) == {n: ["X"] for n in "ABCD"}

    def test_project_enum_base(self, tmp_path: Path):
        src = (
            "import enum\n\n"
            "class Base(str, enum.Enum):\n    pass\n\n"
            "class Mid(Base):\n    pass\n\n"
            "class Kind(Mid):\n    BUG = 'bug'\n"
        )
        # The member-less bases have nothing to draw.
        assert self._enums(tmp_path, src) == {"Kind": ["BUG"]}

    def test_django_choices_base(self, tmp_path: Path):
        src = (
            "from django.db import models\n\n"
            "class LabeledChoices(models.TextChoices):\n    pass\n\n"
            "class Status(LabeledChoices):\n    OPEN = 'o'\n\n"
            "class Ticket(models.Model):\n"
            "    status = models.CharField(max_length=1, choices=Status.choices)\n"
        )
        assert self._enums(tmp_path, src) == {"Status": ["OPEN"]}

    def test_other_bases_are_not_enums(self, tmp_path: Path):
        src = (
            "class Base:\n    X = 1\n\n"
            "class Child(Base):\n    Y = 2\n\n"
            "class Loop(Loop):\n    Z = 3\n"
        )
        assert self._enums(tmp_path, src) == {}

    def test_model_named_like_an_enum_base(self, tmp_path: Path):
        """A scanned model called `Flag` is followed, not taken for enum.Flag."""
        src = (
            "from sqlalchemy import ForeignKey\n"
            "from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column\n\n"
            "class Base(DeclarativeBase):\n    pass\n\n"
            "class Flag(Base):\n"
            "    __tablename__ = 'flag'\n"
            "    id: Mapped[int] = mapped_column(primary_key=True)\n\n"
            "class UserFlag(Flag):\n"
            "    __tablename__ = 'user_flag'\n"
            "    id: Mapped[int] = mapped_column(ForeignKey('flag.id'), primary_key=True)\n"
        )
        (tmp_path / "models.py").write_text(src)
        entities, enums = parse_models_directory(tmp_path)
        assert sorted(entities) == ["Flag", "UserFlag"]
        assert enums == {}

    def test_qualified_model_named_like_an_enum_base(self, tmp_path: Path):
        """`class UserFlag(models.Flag)` follows the scanned `Flag`, not enum.Flag."""
        (tmp_path / "models.py").write_text("class Flag:\n    LIMIT = 5\n")
        (tmp_path / "flags.py").write_text(
            "import enum\n\nimport models\n\n"
            "class UserFlag(models.Flag):\n    LIMIT = 10\n\n"
            "class Perm(enum.Flag):\n    READ = 1\n"
        )
        entities, enums = parse_models_directory(tmp_path, include_patterns=["*.py"])
        assert {name: e.values for name, e in enums.items()} == {"Perm": ["READ"]}
