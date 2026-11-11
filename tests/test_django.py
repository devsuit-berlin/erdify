"""Tests for parsing Django ORM models (#36)."""

from pathlib import Path

import pytest

from erdify.generator import PlantUMLGenerator
from erdify.parser import parse_models_directory


def _edges(output: str) -> list[frozenset[str]]:
    """Return the endpoint pairs of every PlantUML connector line."""
    pairs: list[frozenset[str]] = []
    for line in output.splitlines():
        if "--" not in line or ":" not in line:
            continue
        tokens = line.split(":", 1)[0].split()
        if len(tokens) >= 3:
            pairs.append(frozenset((tokens[0], tokens[-1])))
    return pairs


class TestDjangoEntities:
    def test_models_detected_as_entities(self, django_models_dir: Path):
        entities, _ = parse_models_directory(django_models_dir)

        for name in ("Author", "Profile", "Tag", "Post", "Group", "Membership", "Category"):
            assert name in entities

    def test_entities_have_django_source(self, django_models_dir: Path):
        entities, _ = parse_models_directory(django_models_dir)
        assert entities["Author"].source == "django"

    def test_abstract_base_not_an_entity(self, django_models_dir: Path):
        entities, _ = parse_models_directory(django_models_dir)
        assert "TimestampedModel" not in entities

    def test_abstract_base_fields_inherited(self, django_models_dir: Path):
        entities, _ = parse_models_directory(django_models_dir)
        author_fields = {f.name for f in entities["Author"].fields}
        assert "created_at" in author_fields
        assert "updated_at" in author_fields


class TestDjangoColumns:
    def test_column_types_mapped_to_python(self, django_models_dir: Path):
        """By default Django field types are mapped to readable Python types."""
        entities, _ = parse_models_directory(django_models_dir)
        author_fields = {f.name: f for f in entities["Author"].fields}
        assert author_fields["name"].type_str == "str"  # CharField
        assert author_fields["bio"].type_str == "str"  # TextField
        assert author_fields["created_at"].type_str == "datetime"  # DateTimeField

    def test_unmapped_field_falls_back_to_django_name(self, django_models_dir: Path):
        """Ambiguous/unknown fields keep their Django name rather than fake a type."""
        entities, _ = parse_models_directory(django_models_dir)
        profile_fields = {f.name: f for f in entities["Profile"].fields}
        assert profile_fields["preferences"].type_str == "JSONField"

    def test_implicit_id_primary_key_is_int(self, django_models_dir: Path):
        """Django's implicit id is a BigAutoField -> rendered as int by default."""
        entities, _ = parse_models_directory(django_models_dir)
        author_fields = {f.name: f for f in entities["Author"].fields}
        assert "id" in author_fields
        assert author_fields["id"].is_primary_key is True
        assert author_fields["id"].type_str == "int"


class TestDjangoRawTypes:
    """--django-raw-types keeps the original Django field class names."""

    def test_raw_column_types(self, django_models_dir: Path):
        entities, _ = parse_models_directory(django_models_dir, django_raw_types=True)
        author_fields = {f.name: f for f in entities["Author"].fields}
        assert author_fields["name"].type_str == "CharField"
        assert author_fields["bio"].type_str == "TextField"

    def test_raw_implicit_id_is_bigautofield(self, django_models_dir: Path):
        entities, _ = parse_models_directory(django_models_dir, django_raw_types=True)
        author_fields = {f.name: f for f in entities["Author"].fields}
        assert author_fields["id"].type_str == "BigAutoField"

    def test_db_table_override(self, django_models_dir: Path):
        entities, _ = parse_models_directory(django_models_dir)
        assert entities["Post"].table_name == "blog_post"

    def test_default_table_name_is_app_label_and_lower_case_name(self, django_models_dir: Path):
        """Django's ``<app_label>_<model name>``; the app is the fixture package (#271)."""
        entities, _ = parse_models_directory(django_models_dir)
        assert entities["Author"].table_name == "django_author"


class TestDjangoForeignKey:
    def test_foreign_key_is_modeled_as_id_column(self, django_models_dir: Path):
        entities, _ = parse_models_directory(django_models_dir)
        post_fields = {f.name: f for f in entities["Post"].fields}
        assert "author_id" in post_fields
        assert post_fields["author_id"].is_foreign_key is True
        assert post_fields["author_id"].foreign_table == "django_author.id"

    def test_foreign_key_renders_n_to_one(self, django_models_dir: Path):
        entities, enums = parse_models_directory(django_models_dir)
        output = PlantUMLGenerator(entities, enums).generate()
        assert 'Post }o--|| Author : "author_id"' in output

    def test_self_reference_foreign_key(self, django_models_dir: Path):
        entities, enums = parse_models_directory(django_models_dir)
        output = PlantUMLGenerator(entities, enums).generate()
        assert frozenset(("Category",)) in [frozenset(p) for p in _edges(output)] or any(
            "Category" in line and "--" in line for line in output.splitlines()
        )


class TestDjangoOneToOne:
    def test_one_to_one_renders_with_one_to_one_cardinality(self, django_models_dir: Path):
        """A OneToOneField is a unique ``<name>_id`` FK column, drawn 1:1 (#223)."""
        entities, enums = parse_models_directory(django_models_dir)
        output = PlantUMLGenerator(entities, enums).generate()
        assert 'Profile |o--|| Author : "author_id"' in output


class TestDjangoManyToMany:
    def test_plain_m2m_renders_direct_m2m_edge(self, django_models_dir: Path):
        entities, enums = parse_models_directory(django_models_dir)
        output = PlantUMLGenerator(entities, enums).generate()
        assert 'Post }o--o{ Tag : "tags"' in output

    def test_through_model_is_a_regular_entity(self, django_models_dir: Path):
        entities, enums = parse_models_directory(django_models_dir)
        output = PlantUMLGenerator(entities, enums).generate()
        # Membership is drawn with FK edges to both endpoints.
        assert frozenset(("Membership", "Author")) in _edges(output)
        assert frozenset(("Membership", "Group")) in _edges(output)

    def test_m2m_through_has_no_spurious_direct_edge(self, django_models_dir: Path):
        entities, enums = parse_models_directory(django_models_dir)
        output = PlantUMLGenerator(entities, enums).generate()
        # The Group<->Author M:N goes through Membership, not as a direct edge.
        assert frozenset(("Group", "Author")) not in _edges(output)


class TestDjangoChoices:
    """TextChoices/IntegerChoices render as enums and link via choices=."""

    def test_text_choices_detected_as_enum(self, django_models_dir: Path):
        _, enums = parse_models_directory(django_models_dir)

        assert "Status" in enums
        assert set(enums["Status"].values) == {"DRAFT", "PUBLISHED"}

    def test_integer_choices_detected_as_enum(self, django_models_dir: Path):
        _, enums = parse_models_directory(django_models_dir)

        assert "Priority" in enums
        assert set(enums["Priority"].values) == {"LOW", "HIGH"}

    def test_choices_field_linked_to_enum(self, django_models_dir: Path):
        entities, _ = parse_models_directory(django_models_dir)
        post_fields = {f.name: f for f in entities["Post"].fields}

        assert post_fields["status"].type_str == "Status"
        assert post_fields["priority"].type_str == "Priority"

    def test_choices_enum_rendered_and_linked(self, django_models_dir: Path):
        entities, enums = parse_models_directory(django_models_dir)
        output = PlantUMLGenerator(entities, enums).generate()

        assert "enum Status" in output
        assert "column(status) : Status" in output


class TestDjangoSourcesFilter:
    def test_django_can_be_selected_via_sources(self, django_models_dir: Path):
        entities, _ = parse_models_directory(django_models_dir, sources=["django"])
        assert "Author" in entities

    def test_excluding_django_yields_no_entities(self, django_models_dir: Path):
        entities, _ = parse_models_directory(django_models_dir, sources=["sqlmodel"])
        assert entities == {}


class TestDjangoDefaultTableNames:
    """#271: a table without Meta.db_table is ``<app_label>_<model name, lower-cased>``."""

    MODELS = "from django.db import models\n\n\nclass OrderItem(models.Model):\n    pass\n"

    def _tables(self, root: Path) -> dict[str, str]:
        entities, _ = parse_models_directory(root)
        return {name: entity.table_name for name, entity in entities.items()}

    def _app(self, root: Path, name: str, apps_py: str | None = None) -> Path:
        app = root / name
        app.mkdir(parents=True)
        (app / "models.py").write_text(self.MODELS, encoding="utf-8")
        if apps_py is not None:
            (app / "apps.py").write_text(apps_py, encoding="utf-8")
        return app

    def test_package_name_and_lower_case_model_name(self, tmp_path: Path):
        self._app(tmp_path, "shop")
        assert self._tables(tmp_path) == {"OrderItem": "shop_orderitem"}

    def test_app_config_label(self, tmp_path: Path):
        apps_py = (
            "from django.apps import AppConfig\n\n\n"
            "class ShopConfig(AppConfig):\n"
            '    name = "project.shop"\n'
            '    label = "store"\n'
        )
        self._app(tmp_path, "shop", apps_py)
        assert self._tables(tmp_path) == {"OrderItem": "store_orderitem"}

    def test_app_config_name_without_label(self, tmp_path: Path):
        apps_py = (
            "from django import apps\n\n\n"
            "class ShopConfig(apps.AppConfig):\n"
            '    name = "project.retail"\n'
        )
        self._app(tmp_path, "shop", apps_py)
        assert self._tables(tmp_path) == {"OrderItem": "retail_orderitem"}

    def test_several_configs_use_the_default_one(self, tmp_path: Path):
        apps_py = (
            "from django.apps import AppConfig\n\n\n"
            "class First(AppConfig):\n"
            '    label = "first"\n\n\n'
            "class Second(AppConfig):\n"
            "    default = True\n"
            '    label = "second"\n'
        )
        self._app(tmp_path, "shop", apps_py)
        assert self._tables(tmp_path) == {"OrderItem": "second_orderitem"}

    def test_several_configs_without_default_fall_back_to_the_package(self, tmp_path: Path):
        apps_py = (
            "from django.apps import AppConfig\n\n\n"
            "class First(AppConfig):\n"
            '    label = "first"\n\n\n'
            "class Second(AppConfig):\n"
            '    label = "second"\n'
        )
        self._app(tmp_path, "shop", apps_py)
        assert self._tables(tmp_path) == {"OrderItem": "shop_orderitem"}

    @pytest.mark.parametrize("apps_py", ["class Broken(:\n", "label = 1\x00\n"])
    def test_unreadable_apps_py_falls_back_to_the_package(self, tmp_path: Path, apps_py: str):
        self._app(tmp_path, "shop", apps_py)
        assert self._tables(tmp_path) == {"OrderItem": "shop_orderitem"}

    def test_config_marked_not_default_is_ignored(self, tmp_path: Path):
        apps_py = (
            "from django.apps import AppConfig\n\n\n"
            "class ShopConfig(AppConfig):\n"
            "    default = False\n"
            '    label = "store"\n'
        )
        self._app(tmp_path, "shop", apps_py)
        assert self._tables(tmp_path) == {"OrderItem": "shop_orderitem"}

    def test_remaining_config_after_dropping_non_defaults(self, tmp_path: Path):
        apps_py = (
            "from django.apps import AppConfig\n\n\n"
            "class First(AppConfig):\n"
            "    default = False\n"
            '    label = "first"\n\n\n'
            "class Second(AppConfig):\n"
            '    label = "second"\n'
        )
        self._app(tmp_path, "shop", apps_py)
        assert self._tables(tmp_path) == {"OrderItem": "second_orderitem"}

    @pytest.mark.parametrize("arg", [".", "models.py"])
    def test_relative_input_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, arg: str):
        app = self._app(tmp_path, "shop")
        monkeypatch.chdir(app)
        assert self._tables(Path(arg)) == {"OrderItem": "shop_orderitem"}

    def _package(self, *parts: Path) -> None:
        for part in parts:
            part.mkdir(parents=True, exist_ok=True)
            (part / "__init__.py").write_text("", encoding="utf-8")

    def test_nested_models_package_belongs_to_the_app(self, tmp_path: Path):
        shop = tmp_path / "shop"
        nested = shop / "models" / "billing"
        self._package(shop, shop / "models", nested)
        (nested / "invoice.py").write_text(self.MODELS, encoding="utf-8")
        entities, _ = parse_models_directory(tmp_path, include_patterns=["**/models/**/*.py"])
        assert entities["OrderItem"].table_name == "shop_orderitem"

    @pytest.mark.parametrize("inner", [("models",), ("models", "billing")])
    def test_models_py_inside_a_models_package(self, tmp_path: Path, inner: tuple[str, ...]):
        shop = tmp_path / "shop"
        directory = shop.joinpath(*inner)
        self._package(shop, *(shop.joinpath(*inner[: i + 1]) for i in range(len(inner))))
        (directory / "models.py").write_text(self.MODELS, encoding="utf-8")
        entities, _ = parse_models_directory(tmp_path, include_patterns=["**/models.py"])
        assert entities["OrderItem"].table_name == "shop_orderitem"

    def test_app_named_models(self, tmp_path: Path):
        app = self._app(
            tmp_path,
            "models",
            "from django.apps import AppConfig\n\n\nclass C(AppConfig):\n    pass\n",
        )
        self._package(app)
        assert self._tables(tmp_path) == {"OrderItem": "models_orderitem"}

    def test_models_directory_above_the_project_is_ignored(self, tmp_path: Path):
        self._app(tmp_path / "models" / "project", "shop")
        assert self._tables(tmp_path / "models" / "project") == {"OrderItem": "shop_orderitem"}

    def test_app_config_attributes_from_a_local_base(self, tmp_path: Path):
        apps_py = (
            "from django.apps import AppConfig\n\n\n"
            "class BaseConfig(AppConfig):\n"
            "    default = False\n"
            '    label = "store"\n\n\n'
            "class ShopConfig(BaseConfig):\n"
            "    default = True\n"
        )
        self._app(tmp_path, "shop", apps_py)
        assert self._tables(tmp_path) == {"OrderItem": "store_orderitem"}

    def test_last_assignment_wins(self, tmp_path: Path):
        apps_py = (
            "from django.apps import AppConfig\n\n\n"
            "class ShopConfig(AppConfig):\n"
            '    label = "shop"\n'
            '    label = "store"\n'
        )
        self._app(tmp_path, "shop", apps_py)
        assert self._tables(tmp_path) == {"OrderItem": "store_orderitem"}

    def test_non_literal_last_assignment_falls_back(self, tmp_path: Path):
        apps_py = (
            "from django.apps import AppConfig\n\n\n"
            "class ShopConfig(AppConfig):\n"
            '    label = "store"\n'
            "    label = compute_label()\n"
        )
        self._app(tmp_path, "shop", apps_py)
        assert self._tables(tmp_path) == {"OrderItem": "shop_orderitem"}

    def test_models_package_belongs_to_its_parent_app(self, tmp_path: Path):
        models_pkg = tmp_path / "shop" / "models"
        models_pkg.mkdir(parents=True)
        (models_pkg / "order.py").write_text(self.MODELS, encoding="utf-8")
        entities, _ = parse_models_directory(tmp_path, include_patterns=["**/models/*.py"])
        assert entities["OrderItem"].table_name == "shop_orderitem"

    ANNOTATED_APP_LABEL = """
from django.db import models


class OrderItem(models.Model):
    class Meta:
        app_label: str = "sales"
"""

    REASSIGNED_APP_LABEL = """
from django.db import models


class OrderItem(models.Model):
    class Meta:
        app_label = "shop"
        app_label = "sales"
"""

    @pytest.mark.parametrize("source", [ANNOTATED_APP_LABEL, REASSIGNED_APP_LABEL])
    def test_meta_app_label_annotated_or_reassigned(self, tmp_path: Path, source: str):
        app = self._app(tmp_path, "shop")
        (app / "models.py").write_text(source, encoding="utf-8")
        assert self._tables(tmp_path) == {"OrderItem": "sales_orderitem"}

    def test_meta_app_label_wins(self, tmp_path: Path):
        app = self._app(tmp_path, "shop")
        (app / "models.py").write_text(
            "from django.db import models\n\n\n"
            "class OrderItem(models.Model):\n"
            "    class Meta:\n"
            '        app_label = "sales"\n',
            encoding="utf-8",
        )
        assert self._tables(tmp_path) == {"OrderItem": "sales_orderitem"}

    def test_foreign_key_uses_the_target_app(self, tmp_path: Path):
        self._app(tmp_path, "shop")
        billing = tmp_path / "billing"
        billing.mkdir()
        (billing / "models.py").write_text(
            "from django.db import models\n\n\n"
            "class Invoice(models.Model):\n"
            '    item = models.ForeignKey("shop.OrderItem", on_delete=models.CASCADE)\n',
            encoding="utf-8",
        )
        entities, _ = parse_models_directory(tmp_path)
        assert entities["Invoice"].table_name == "billing_invoice"
        fk = next(f for f in entities["Invoice"].fields if f.name == "item_id")
        assert fk.foreign_table == "shop_orderitem.id"
