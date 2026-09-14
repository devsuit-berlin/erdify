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


class TestModelDerivedSchemas:
    """ninja-style ModelSchema classes are skipped, not drawn empty (#171)."""

    @staticmethod
    def _write(tmp_path: Path, body: str) -> Path:
        (tmp_path / "models.py").write_text(body)
        return tmp_path

    DJANGO_MODEL = (
        "from django.db import models\n"
        "from ninja import ModelSchema\n\n\n"
        "class User(models.Model):\n"
        "    name = models.CharField(max_length=100)\n"
        "    email = models.EmailField()\n\n\n"
    )

    def test_meta_form_is_skipped(self, tmp_path: Path, capsys):
        """django-ninja's ModelSchema uses an inner Meta."""
        root = self._write(
            tmp_path,
            self.DJANGO_MODEL + "class UserSchema(ModelSchema):\n"
            '    class Meta:\n        model = User\n        fields = ["id", "name"]\n',
        )

        entities, _ = parse_models_directory(root, base_classes=["ModelSchema"])

        assert "User" in entities
        assert "UserSchema" not in entities
        err = capsys.readouterr().err
        assert "skipped UserSchema" in err
        assert "Meta.model (User)" in err
        assert "issues/171" in err

    def test_config_form_is_skipped(self, tmp_path: Path):
        """ninja-schema uses an inner Config instead."""
        root = self._write(
            tmp_path,
            self.DJANGO_MODEL + "class UserSchema(ModelSchema):\n"
            '    class Config:\n        model = User\n        include = ["id"]\n',
        )

        entities, _ = parse_models_directory(root, base_classes=["ModelSchema"])

        assert "UserSchema" not in entities

    def test_partial_schema_is_also_skipped(self, tmp_path: Path):
        """Explicit fields alongside Meta.model would still be an incomplete entity."""
        root = self._write(
            tmp_path,
            self.DJANGO_MODEL + "class UserSchema(ModelSchema):\n"
            "    display_name: str\n\n"
            "    class Meta:\n        model = User\n",
        )

        entities, _ = parse_models_directory(root, base_classes=["ModelSchema"])

        assert "UserSchema" not in entities

    def test_qualified_model_reference(self, tmp_path: Path, capsys):
        """model = app.User resolves to the attribute name for the message."""
        root = self._write(
            tmp_path,
            self.DJANGO_MODEL + "class UserSchema(ModelSchema):\n"
            "    class Meta:\n        model = accounts.User\n",
        )

        parse_models_directory(root, base_classes=["ModelSchema"])

        assert "Meta.model (User)" in capsys.readouterr().err

    def test_ordinary_pydantic_model_is_untouched(self, tmp_path: Path, capsys):
        """A nested config class without `model =` must not trigger the guard."""
        root = self._write(
            tmp_path,
            "from pydantic import BaseModel\n\n\n"
            "class Widget(BaseModel):\n"
            "    id: int\n"
            "    name: str\n\n"
            "    class Config:\n        frozen = True\n",
        )

        entities, _ = parse_models_directory(root)

        assert "Widget" in entities
        assert "skipped" not in capsys.readouterr().err

    def test_django_meta_is_untouched(self, tmp_path: Path, capsys):
        """Django's own class Meta must not be mistaken for a schema config."""
        root = self._write(
            tmp_path,
            "from django.db import models\n\n\n"
            "class User(models.Model):\n"
            "    name = models.CharField(max_length=100)\n\n"
            '    class Meta:\n        db_table = "user"\n',
        )

        entities, _ = parse_models_directory(root)

        assert entities["User"].table_name == "user"
        assert "skipped" not in capsys.readouterr().err

    def test_cli_reports_it(self, tmp_path: Path, capsys):
        """The warning reaches stderr through the CLI too."""
        root = self._write(
            tmp_path,
            self.DJANGO_MODEL + "class UserSchema(ModelSchema):\n"
            "    class Meta:\n        model = User\n",
        )

        with patch.object(sys, "argv", ["erdify", str(root), "--base-classes", "ModelSchema"]):
            result = main()

        assert result == 0
        assert "skipped UserSchema" in capsys.readouterr().err
