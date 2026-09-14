"""Tests for --base-classes: Pydantic bases defined outside the scanned files."""

import sys
from pathlib import Path
from unittest.mock import patch

from erdify.cli import main
from erdify.parser import parse_models_directory

FIXTURE = Path(__file__).parent / "fixtures" / "base_classes"


class TestBaseClassesParser:
    """parse_models_directory(base_classes=...)."""

    def test_unscanned_base_is_invisible_by_default(self):
        """Without the option the classes are skipped, which is the bug."""
        entities, _ = parse_models_directory(FIXTURE)

        assert entities == {}

    def test_named_base_is_recognized(self):
        """Naming the base makes its direct subclasses Pydantic entities."""
        entities, _ = parse_models_directory(FIXTURE, base_classes=["Schema"])

        assert "AuthorOut" in entities
        assert "BookOut" in entities
        assert entities["AuthorOut"].source == "pydantic"

    def test_transitive_through_a_local_intermediate(self):
        """A class reaching the named base via a scanned intermediate counts."""
        entities, _ = parse_models_directory(FIXTURE, base_classes=["Schema"])

        assert "ReviewOut" in entities
        # Fields from the intermediate are inherited as usual.
        assert [f.name for f in entities["ReviewOut"].fields] == [
            "created_at",
            "id",
            "rating",
        ]

    def test_attribute_form_of_the_base(self):
        """``module.Schema`` is matched on the attribute name, like BaseModel is."""
        entities, _ = parse_models_directory(FIXTURE, base_classes=["Schema"])

        assert "QualifiedOut" in entities

    def test_unrelated_classes_stay_out(self):
        """Naming a base must not sweep in every class in the file."""
        entities, _ = parse_models_directory(FIXTURE, base_classes=["Schema"])

        assert "NotAModel" not in entities

    def test_a_name_that_matches_nothing_changes_nothing(self):
        """An unused name is inert rather than an error."""
        entities, _ = parse_models_directory(FIXTURE, base_classes=["NoSuchBase"])

        assert entities == {}

    def test_infer_keys_applies_to_the_recognized_models(self):
        """They are ordinary Pydantic entities, so --infer-keys works on them."""
        entities, _ = parse_models_directory(FIXTURE, base_classes=["Schema"], infer_keys=True)

        book = entities["BookOut"]
        assert next(f for f in book.fields if f.name == "id").is_primary_key
        assert next(f for f in book.fields if f.name == "author_id").is_foreign_key

    def test_sources_filter_still_applies(self):
        """They classify as pydantic, so --sources can exclude them."""
        entities, _ = parse_models_directory(FIXTURE, base_classes=["Schema"], sources=["sqlmodel"])

        assert entities == {}


class TestBaseClassesCLI:
    """--base-classes and [tool.erdify] base_classes."""

    def test_cli_flag(self, capsys):
        """--base-classes accepts one or more names."""
        with patch.object(sys, "argv", ["erdify", str(FIXTURE), "--base-classes", "Schema"]):
            result = main()

        assert result == 0
        assert "AuthorOut" in capsys.readouterr().out

    def test_cli_without_the_flag_reports_an_empty_result(self, capsys):
        """The default path is unchanged: nothing recognized, non-zero exit."""
        with patch.object(sys, "argv", ["erdify", str(FIXTURE)]):
            result = main()

        assert result == 1
        assert "No tables found" in capsys.readouterr().err

    def test_pyproject_config(self, tmp_path: Path, capsys):
        """[tool.erdify] base_classes works like the flag."""
        (tmp_path / "pyproject.toml").write_text('[tool.erdify]\nbase_classes = ["BaseSchema"]\n')
        (tmp_path / "models.py").write_text(
            "from company.schemas import BaseSchema\n\n\n"
            "class Widget(BaseSchema):\n    id: int\n    name: str\n"
        )

        with patch.object(sys, "argv", ["erdify", str(tmp_path)]):
            result = main()

        assert result == 0
        assert "Widget" in capsys.readouterr().out
