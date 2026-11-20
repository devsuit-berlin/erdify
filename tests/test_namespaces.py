"""Same-name model classes in different modules stay apart (#367)."""

from pathlib import Path

import pytest

from erdify import diagram_edges, generate_plantuml, parse_models_directory
from erdify.config import EntityInfo
from erdify.parser.common import original_class_name


def _write(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _packages(root: Path, *names: str) -> None:
    for name in names:
        (root / name).mkdir(parents=True, exist_ok=True)
        (root / name / "__init__.py").write_text("", encoding="utf-8")


def _edges(entities: dict[str, EntityInfo]) -> list[tuple[str, str, str]]:
    return [(e.from_entity, e.to_entity, e.label) for e in diagram_edges(entities)]


ADDRESS = {
    "billing/models.py": "from pydantic import BaseModel\n\n\nclass Address(BaseModel):\n"
    "    street: str\n",
    "shipping/models.py": "from pydantic import BaseModel\n\n\nclass Address(BaseModel):\n"
    "    city: str\n",
}


class TestReferences:
    @pytest.fixture
    def root(self, tmp_path: Path) -> Path:
        _packages(tmp_path, "billing", "shipping", "orders")
        _write(tmp_path, ADDRESS)
        return tmp_path

    def _order(self, root: Path, body: str) -> list[tuple[str, str, str]]:
        _write(root, {"orders/models.py": "from pydantic import BaseModel\n" + body})
        entities, _ = parse_models_directory(root)
        return _edges(dict(entities))

    def test_imported_name(self, root: Path) -> None:
        edges = self._order(
            root,
            "from billing.models import Address\n\n\n"
            "class Order(BaseModel):\n    address: Address\n",
        )
        assert edges == [("Order", "billing.models.Address", "address")]

    def test_aliased_import_and_relative_import(self, root: Path) -> None:
        edges = self._order(
            root,
            "from ..shipping.models import Address as ShipTo\n\n\n"
            "class Order(BaseModel):\n    ship_to: ShipTo\n",
        )
        assert edges == [("Order", "shipping.models.Address", "ship_to")]

    def test_module_attribute_and_quoted_forward_reference(self, root: Path) -> None:
        edges = self._order(
            root,
            "import billing.models\nfrom shipping import models as shipping\n\n\n"
            "class Order(BaseModel):\n"
            "    billing_address: billing.models.Address\n"
            '    shipping_addresses: list["shipping.Address"]\n',
        )
        assert edges == [
            ("Order", "billing.models.Address", "billing_address"),
            ("Order", "shipping.models.Address", "shipping_addresses"),
        ]

    def test_star_import(self, root: Path) -> None:
        edges = self._order(
            root,
            "from shipping.models import *\n\n\nclass Order(BaseModel):\n    address: Address\n",
        )
        assert edges == [("Order", "shipping.models.Address", "address")]

    def test_own_module_wins(self, root: Path) -> None:
        _write(
            root,
            {
                "billing/models.py": ADDRESS["billing/models.py"]
                + "\n\nclass Invoice(BaseModel):\n    address: Address\n"
            },
        )
        entities, _ = parse_models_directory(root)
        assert _edges(dict(entities)) == [("Invoice", "billing.models.Address", "address")]

    def test_unresolved_reference_is_reported_and_not_drawn(
        self, root: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        edges = self._order(root, "\n\nclass Order(BaseModel):\n    address: 'Address'\n")

        assert edges == []
        err = capsys.readouterr().err
        assert "orders/models.py refers to 'Address', which is defined in" in err
        assert "billing/models.py and shipping/models.py" in err

    def test_module_alias_and_unparseable_annotation_strings(self, root: Path) -> None:
        edges = self._order(
            root,
            "from typing import Literal\nimport shipping.models as sm\n\n\n"
            "class Order(BaseModel):\n"
            "    address: sm.Address\n"
            '    kind: Literal["not an expression!"]\n\n\n'
            "def make(address: sm.Address) -> None:\n    pass\n",
        )
        assert edges == [("Order", "shipping.models.Address", "address")]

    def test_import_matching_two_modules_is_unresolved(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # No packages: `from models import Address` could be either file.
        _write(tmp_path, {"a/models.py": ADDRESS["billing/models.py"]})
        _write(tmp_path, {"b/models.py": ADDRESS["shipping/models.py"]})
        _write(
            tmp_path,
            {
                "c/models.py": "from pydantic import BaseModel\nfrom models import Address\n\n\n"
                "class Order(BaseModel):\n    address: Address\n"
            },
        )

        entities, _ = parse_models_directory(tmp_path)

        assert sorted(entities) == ["Order", "a.models.Address", "b.models.Address"]
        assert _edges(dict(entities)) == []
        assert "c/models.py refers to 'Address'" in capsys.readouterr().err


class TestFrameworks:
    def test_django_app_labels_and_same_app_strings(self, tmp_path: Path) -> None:
        _packages(tmp_path, "billing", "shipping")
        _write(
            tmp_path,
            {
                "billing/models.py": "from django.db import models\n\n\n"
                "class Profile(models.Model):\n    iban = models.CharField(max_length=34)\n\n\n"
                "class Invoice(models.Model):\n"
                '    profile = models.ForeignKey("Profile", on_delete=models.CASCADE)\n'
                "    shipping_profile = models.ForeignKey(\n"
                '        "shipping.Profile", on_delete=models.CASCADE\n    )\n',
                "shipping/models.py": "from django.db import models\n\n\n"
                "class Profile(models.Model):\n    street = models.CharField(max_length=99)\n\n\n"
                "class Parcel(models.Model):\n"
                "    profile = models.ForeignKey(Profile, on_delete=models.CASCADE)\n",
            },
        )

        entities, _ = parse_models_directory(tmp_path)

        tables = {name: e.table_name for name, e in entities.items()}
        assert tables["billing.models.Profile"] == "billing_profile"
        assert tables["shipping.models.Profile"] == "shipping_profile"
        assert _edges(dict(entities)) == [
            ("Invoice", "billing.models.Profile", "profile_id"),
            ("Invoice", "shipping.models.Profile", "shipping_profile_id"),
            ("Parcel", "shipping.models.Profile", "profile_id"),
        ]

    def test_django_strings_from_another_file_of_the_app(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _packages(tmp_path, "billing", "shipping", "crm")
        profile = (
            "from django.db import models\n\n\n"
            "class Profile(models.Model):\n    name = models.CharField(max_length=9)\n"
        )
        _write(
            tmp_path,
            {
                "billing/models.py": profile,
                "shipping/models.py": profile,
                "billing/extra.py": "from django.db import models\n\n\n"
                "class Payment(models.Model):\n"
                '    profile = models.ForeignKey("Profile", on_delete=models.CASCADE)\n'
                "    other = models.ForeignKey(\n"
                '        to="shipping.Profile", on_delete=models.CASCADE, related_name="+"\n'
                "    )\n",
                "crm/models.py": "from django.db import models\n\n\n"
                "class Lead(models.Model):\n"
                '    profile = models.ForeignKey("Profile", on_delete=models.CASCADE)\n',
            },
        )

        entities, _ = parse_models_directory(tmp_path, include_patterns=["**/*.py"])

        assert _edges(dict(entities)) == [
            ("Payment", "billing.models.Profile", "profile_id"),
            ("Payment", "shipping.models.Profile", "other_id"),
        ]
        assert "crm/models.py refers to 'Profile'" in capsys.readouterr().err

    def test_sqlmodel_default_table_names_and_schema_edges(self, tmp_path: Path) -> None:
        _packages(tmp_path, "core", "mart")
        _write(
            tmp_path,
            {
                "core/models.py": "from sqlmodel import Field, SQLModel\n\n\n"
                "class Customer(SQLModel, table=True):\n"
                '    __table_args__ = {"schema": "core"}\n'
                "    id: int = Field(primary_key=True)\n",
                "mart/models.py": "from sqlmodel import Field, Relationship, SQLModel\n"
                "from core.models import Customer as CoreCustomer\n\n\n"
                "class Customer(SQLModel, table=True):\n"
                '    __table_args__ = {"schema": "mart"}\n'
                "    id: int = Field(primary_key=True)\n"
                '    core_id: int = Field(foreign_key="core.customer.id")\n'
                "    core: CoreCustomer = Relationship()\n",
            },
        )

        entities, _ = parse_models_directory(tmp_path)

        assert {name: (e.schema, e.table_name) for name, e in entities.items()} == {
            "core.models.Customer": ("core", "customer"),
            "mart.models.Customer": ("mart", "customer"),
        }
        assert _edges(dict(entities)) == [
            ("mart.models.Customer", "core.models.Customer", "core_id")
        ]
        plantuml = generate_plantuml(dict(entities))
        assert 'entity "core.customer" as core_models_Customer {' in plantuml

    def test_sqlalchemy_relationship_string_with_module_path(self, tmp_path: Path) -> None:
        header = (
            "from sqlalchemy import ForeignKey\n"
            "from sqlalchemy.orm import Mapped, mapped_column, relationship\n"
            "from base import Base\n\n\n"
        )
        _packages(tmp_path, "a", "b")
        _write(
            tmp_path,
            {
                "base.py": "from sqlalchemy.orm import DeclarativeBase\n\n\n"
                "class Base(DeclarativeBase):\n    pass\n",
                "a/models.py": header + "class Tag(Base):\n    __tablename__ = 'a_tag'\n"
                "    id: Mapped[int] = mapped_column(primary_key=True)\n",
                "b/models.py": header + "class Tag(Base):\n    __tablename__ = 'b_tag'\n"
                "    id: Mapped[int] = mapped_column(primary_key=True)\n"
                "    a_id: Mapped[int] = mapped_column(ForeignKey('a_tag.id'))\n"
                "    a: Mapped['a.models.Tag'] = relationship('a.models.Tag')\n",
            },
        )

        entities, _ = parse_models_directory(tmp_path, include_patterns=["**/*.py"])

        assert set(entities) >= {"a.models.Tag", "b.models.Tag"}
        assert _edges(dict(entities)) == [("b.models.Tag", "a.models.Tag", "a_id")]


class TestNoCollision:
    def test_unique_names_are_unchanged(self, tmp_path: Path) -> None:
        _packages(tmp_path, "billing")
        _write(tmp_path, {"billing/models.py": ADDRESS["billing/models.py"]})

        entities, _ = parse_models_directory(tmp_path)

        assert list(entities) == ["Address"]

    def test_same_name_non_models_are_not_namespaced(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            {
                "a/models.py": "from pydantic import BaseModel\n\n\nclass Address(BaseModel):\n"
                "    city: str\n\n\nclass Meta:\n    pass\n",
                "b/models.py": "class Meta:\n    pass\n",
            },
        )

        entities, _ = parse_models_directory(tmp_path)

        assert list(entities) == ["Address"]


def test_original_class_name() -> None:
    assert original_class_name("Address__erdify12") == "Address"
    assert original_class_name("Address") == "Address"
    assert original_class_name("My__erdifyThing") == "My__erdifyThing"


class TestReviewCases:
    """Cases a review found (#367)."""

    @pytest.fixture
    def root(self, tmp_path: Path) -> Path:
        _packages(tmp_path, "billing", "shipping", "orders")
        _write(tmp_path, ADDRESS)
        return tmp_path

    def test_imported_module_alias(self, root: Path) -> None:
        _write(
            root,
            {
                "orders/models.py": "from pydantic import BaseModel\n"
                "from billing import models as bm\nfrom ..shipping import models\n\n\n"
                "class Order(BaseModel):\n    billing: bm.Address\n    shipping: models.Address\n"
            },
        )

        entities, _ = parse_models_directory(root)

        assert _edges(dict(entities)) == [
            ("Order", "billing.models.Address", "billing"),
            ("Order", "shipping.models.Address", "shipping"),
        ]

    def test_names_imported_from_unscanned_modules_are_not_reported(
        self, root: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(
            root,
            {
                "orders/models.py": "from pydantic import BaseModel\n"
                "from vendor.geo import Address\n\n\n"
                "class Order(BaseModel):\n    address: Address\n"
            },
        )

        parse_models_directory(root)

        assert "refers to" not in capsys.readouterr().err

    def test_an_earlier_same_file_definition_leaves_no_entity(self, root: Path) -> None:
        _write(
            root,
            {
                "billing/models.py": "from pydantic import BaseModel\n\n\n"
                "class Address(BaseModel):\n    old: str\n\n\n" + ADDRESS["billing/models.py"]
            },
        )

        entities, _ = parse_models_directory(root)

        assert sorted(entities) == ["billing.models.Address", "shipping.models.Address"]
        assert [f.name for f in entities["billing.models.Address"].fields] == ["street"]

    def test_default_values_show_the_display_name(self, root: Path) -> None:
        _write(
            root,
            {
                "billing/models.py": "from pydantic import Field\n"
                + ADDRESS["billing/models.py"]
                + "    KIND: str = 'home'\n\n\n"
                "class Invoice(BaseModel):\n    kind: str = Field(default=Address.KIND)\n"
            },
        )

        entities, _ = parse_models_directory(root)

        kind = next(f for f in entities["Invoice"].fields if f.name == "kind")
        assert kind.default_value == "billing.models.Address.KIND"

    def test_a_same_module_key_wins_among_same_table_models(self, root: Path) -> None:
        _write(
            root,
            {
                "billing/models.py": ADDRESS["billing/models.py"] + "\n\n"
                "class Invoice(BaseModel):\n    id: int\n    address_id: int\n",
                "shipping/models.py": ADDRESS["shipping/models.py"] + "\n\n"
                "class Parcel(BaseModel):\n    id: int\n    address_id: int\n",
            },
        )

        entities, _ = parse_models_directory(root, infer_keys=True)

        assert _edges(dict(entities)) == [
            ("Invoice", "billing.models.Address", "address_id"),
            ("Parcel", "shipping.models.Address", "address_id"),
        ]

    def test_base_classes_defined_in_two_modules(self, tmp_path: Path) -> None:
        _packages(tmp_path, "a", "b")
        schema = "class Schema:\n    pass\n\n\n"
        _write(
            tmp_path,
            {
                "a/models.py": schema + "class Address(Schema):\n    street: str\n",
                "b/models.py": schema + "class Parcel(Schema):\n    weight: int\n",
            },
        )

        entities, _ = parse_models_directory(tmp_path, base_classes=["Schema"])

        assert {"Address", "Parcel"} <= set(entities)

    def test_sources_decide_what_collides(self, tmp_path: Path) -> None:
        _packages(tmp_path, "a", "b")
        _write(
            tmp_path,
            {
                "a/models.py": "from django.db import models\n\n\n"
                "class Address(models.Model):\n    street = models.CharField(max_length=9)\n",
                "b/models.py": ADDRESS["shipping/models.py"],
            },
        )

        entities, _ = parse_models_directory(tmp_path, sources=["django"])

        assert list(entities) == ["Address"]

    def test_a_python_model_still_wins_over_a_sql_table_of_its_name(self, root: Path) -> None:
        pytest.importorskip("sqlglot")
        _write(root, {"schema.sql": "CREATE TABLE Address (id INT PRIMARY KEY);\n"})

        entities, _ = parse_models_directory(root, include_patterns=["models.py", "*.sql"])

        assert sorted(entities) == ["billing.models.Address", "shipping.models.Address"]

    def test_django_model_names_in_any_case(self, tmp_path: Path) -> None:
        _packages(tmp_path, "billing", "shipping")
        profile = (
            "from django.db import models\n\n\n"
            "class Profile(models.Model):\n    name = models.CharField(max_length=9)\n"
        )
        _write(
            tmp_path,
            {
                "billing/models.py": profile + "\n\nclass Invoice(models.Model):\n"
                '    own = models.ForeignKey("profile", on_delete=models.CASCADE)\n'
                "    other = models.ForeignKey(\n"
                '        "shipping.profile", on_delete=models.CASCADE, related_name="+"\n    )\n',
                "shipping/models.py": profile,
            },
        )

        entities, _ = parse_models_directory(tmp_path)

        assert _edges(dict(entities)) == [
            ("Invoice", "billing.models.Profile", "own_id"),
            ("Invoice", "shipping.models.Profile", "other_id"),
        ]

    def test_a_symlink_out_of_the_scan_keeps_working(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        root = tmp_path / "root"
        _write(outside, {"models.py": ADDRESS["shipping/models.py"]})
        _write(root, {"a/models.py": ADDRESS["billing/models.py"]})
        (root / "b").mkdir()
        try:
            (root / "b" / "models.py").symlink_to(outside / "models.py")
        except OSError:
            pytest.skip("no symlinks here")

        entities, _ = parse_models_directory(root)

        assert len(entities) == 2


class TestSecondReview:
    """Cases a second review found (#367)."""

    @pytest.fixture
    def root(self, tmp_path: Path) -> Path:
        _packages(tmp_path, "billing", "shipping", "orders")
        _write(tmp_path, ADDRESS)
        return tmp_path

    def test_a_package_re_export_is_followed(self, tmp_path: Path) -> None:
        _packages(tmp_path, "shop", "shop/models", "shipping", "orders")
        _write(
            tmp_path,
            {
                "shop/models/__init__.py": "from .address import Address\n",
                "shop/models/address.py": ADDRESS["billing/models.py"],
                "shipping/models.py": ADDRESS["shipping/models.py"],
                "orders/models.py": "from pydantic import BaseModel\n"
                "from shop.models import Address\n\n\n"
                "class Order(BaseModel):\n    address: Address\n",
            },
        )

        entities, _ = parse_models_directory(
            tmp_path, include_patterns=["models.py", "shop/models/*.py"]
        )

        assert _edges(dict(entities)) == [("Order", "shop.models.address.Address", "address")]

    def test_literal_values_stay_as_written(
        self, root: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(
            root,
            {
                "orders/models.py": "from typing import Annotated, Literal\n"
                "from pydantic import BaseModel, Field\n\n\n"
                "class Order(BaseModel):\n"
                '    kind: Literal["Address"]\n'
                '    note: Annotated[str, Field(description="Address")]\n'
            },
        )

        entities, _ = parse_models_directory(root)

        kind = next(f for f in entities["Order"].fields if f.name == "kind")
        assert "Address" in kind.type_str and "models" not in kind.type_str
        assert "refers to" not in capsys.readouterr().err

    def test_own_non_model_binding_and_unmatched_dotted_strings_are_quiet(
        self, root: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(
            root,
            {
                "orders/models.py": "from pydantic import BaseModel\n\n\n"
                "class Address:\n    pass\n\n\n"
                "class Order(BaseModel):\n    note: str\n    other: 'x.y.Address'\n\n\n"
                "def make() -> Address:\n    return Address()\n"
            },
        )

        parse_models_directory(root)

        assert "refers to" not in capsys.readouterr().err

    def test_sqlalchemy_foreign_key_strings_are_never_rewritten(self, tmp_path: Path) -> None:
        header = (
            "from sqlalchemy import ForeignKey\n"
            "from sqlalchemy.orm import Mapped, mapped_column\nfrom base import Base\n\n\n"
        )
        _packages(tmp_path, "a", "b")
        _write(
            tmp_path,
            {
                "base.py": "from sqlalchemy.orm import DeclarativeBase\n\n\n"
                "class Base(DeclarativeBase):\n    pass\n",
                "a/models.py": header + "class Account(Base):\n    __tablename__ = 'account'\n"
                "    id: Mapped[int] = mapped_column(primary_key=True)\n",
                "b/models.py": header + "class Account(Base):\n"
                "    __tablename__ = 'b_account'\n"
                "    id: Mapped[int] = mapped_column(primary_key=True)\n"
                "    a_id: Mapped[int] = mapped_column(ForeignKey('a.account'))\n",
            },
        )

        entities, _ = parse_models_directory(tmp_path, include_patterns=["**/*.py"])

        a_id = next(f for f in entities["b.models.Account"].fields if f.name == "a_id")
        assert a_id.foreign_table == "a.account"

    def test_django_meta_app_label(self, tmp_path: Path) -> None:
        _packages(tmp_path, "billing", "shipping")
        _write(
            tmp_path,
            {
                "billing/models.py": "from django.db import models\n\n\n"
                "class Profile(models.Model):\n    name = models.CharField(max_length=9)\n\n"
                "    class Meta:\n        app_label = 'invoicing'\n",
                "shipping/models.py": "from django.db import models\n\n\n"
                "class Profile(models.Model):\n    name = models.CharField(max_length=9)\n\n\n"
                "class Parcel(models.Model):\n"
                '    owner = models.ForeignKey("invoicing.Profile", on_delete=models.CASCADE)\n',
            },
        )

        entities, _ = parse_models_directory(tmp_path)

        assert _edges(dict(entities)) == [("Parcel", "billing.models.Profile", "owner_id")]

    def test_a_reference_to_an_unbuilt_namesake_keeps_its_module(self, root: Path) -> None:
        _write(
            root,
            {
                "shipping/models.py": "from dataclasses import dataclass\n\n\n"
                "@dataclass\nclass Address:\n    city: str\n",
                "orders/models.py": "from pydantic import BaseModel\n"
                "from shipping.models import Address\n\n\n"
                "class Order(BaseModel):\n    address: Address\n",
            },
        )

        entities, _ = parse_models_directory(root, sources=["pydantic"])

        assert sorted(entities) == ["Address", "Order"]  # billing's, the only one built
        assert entities["Order"].relationships[0][0] == "shipping.models.Address"


def test_same_module_preference_is_only_for_namesakes() -> None:
    from erdify.config import FieldInfo

    def entity(name: str, module: str, fields: list[FieldInfo] | None = None) -> EntityInfo:
        return EntityInfo(name=name, table_name="article", module=module, fields=fields or [])

    fk = FieldInfo("article_id", "int", is_foreign_key=True, foreign_table="article.id")
    entities = {
        "Article": entity("Article", "blog.models"),
        "ArticleStats": entity("ArticleStats", "reports.models"),
        "Flag": EntityInfo(name="Flag", table_name="flag", module="reports.models", fields=[fk]),
    }

    assert _edges(entities) == [("Flag", "Article", "article_id")]


class TestThirdReview:
    """Cases a third review found (#367)."""

    def test_a_scanned_module_binding_the_name_otherwise_is_quiet(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _packages(tmp_path, "billing", "shipping", "orders")
        _write(tmp_path, ADDRESS)
        _write(
            tmp_path,
            {
                "orders/forms.py": "class Address:\n    pass\n",
                "orders/models.py": "from pydantic import BaseModel\n"
                "from orders.forms import Address\n\n\n"
                "class Order(BaseModel):\n    note: str\n\n\n"
                "def make() -> Address:\n    return Address()\n",
            },
        )

        parse_models_directory(tmp_path, include_patterns=["**/*.py"])

        assert "refers to" not in capsys.readouterr().err

    def test_a_bare_django_name_uses_the_referencing_models_app_label(self, tmp_path: Path) -> None:
        _packages(tmp_path, "billing", "shipping")
        meta = "\n    class Meta:\n        app_label = 'invoicing'\n"
        _write(
            tmp_path,
            {
                "billing/models.py": "from django.db import models\n\n\n"
                "class Profile(models.Model):\n    name = models.CharField(max_length=9)\n" + meta,
                "billing/other.py": "from django.db import models\n\n\n"
                "class Payment(models.Model):\n"
                '    profile = models.ForeignKey("Profile", on_delete=models.CASCADE)\n' + meta,
                "shipping/models.py": "from django.db import models\n\n\n"
                "class Profile(models.Model):\n    name = models.CharField(max_length=9)\n",
            },
        )

        entities, _ = parse_models_directory(tmp_path, include_patterns=["**/*.py"])

        assert _edges(dict(entities)) == [("Payment", "billing.models.Profile", "profile_id")]


def test_namesake_preference_ignores_a_sql_table_of_the_same_name() -> None:
    from erdify.config import FieldInfo

    def address(name: str, module: str | None, source: str) -> EntityInfo:
        return EntityInfo(name=name, table_name="address", module=module, source=source)

    fk = FieldInfo("address_id", "int", is_foreign_key=True, foreign_table="address.id")
    entities = {
        "billing.models.Address": address("billing.models.Address", "billing.models", "pydantic"),
        "shipping.models.Address": address(
            "shipping.models.Address", "shipping.models", "pydantic"
        ),
        "address": address("address", None, "sql"),
        "Order": EntityInfo(
            name="Order", table_name="order", module="shipping.models", fields=[fk]
        ),
    }

    assert _edges(entities) == [("Order", "shipping.models.Address", "address_id")]


class TestReExports:
    def _layout(self, root: Path, billing_init: str) -> None:
        _packages(root, "billing", "billing/models", "shipping", "orders")
        _write(
            root,
            {
                "billing/models/__init__.py": billing_init,
                "billing/models/address.py": ADDRESS["billing/models.py"],
                "billing/models/invoice.py": "from pydantic import BaseModel\n\n\n"
                "class Invoice(BaseModel):\n    number: str\n",
                "shipping/models.py": ADDRESS["shipping/models.py"],
                "orders/models.py": "from pydantic import BaseModel\n"
                "from billing.models import Address\n\n\n"
                "class Order(BaseModel):\n    address: Address\n",
            },
        )

    def _parse(self, root: Path) -> dict[str, EntityInfo]:
        entities, _ = parse_models_directory(
            root, include_patterns=["models.py", "billing/models/*.py"]
        )
        return dict(entities)

    def test_star_re_exports_are_followed(self, tmp_path: Path) -> None:
        self._layout(tmp_path, "from .invoice import *\nfrom .address import *\n")

        edges = _edges(self._parse(tmp_path))

        assert edges == [("Order", "billing.models.address.Address", "address")]

    def test_a_sibling_with_type_checking_imports_does_not_spoil_a_star(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._layout(tmp_path, "from .address import *\nfrom .invoice import *\n")
        _write(
            tmp_path,
            {
                "billing/models/invoice.py": "from typing import TYPE_CHECKING\n"
                "from pydantic import BaseModel\n\n"
                "if TYPE_CHECKING:\n    from .address import Address\n\n\n"
                "def load():\n    from .address import Address\n    return Address\n\n\n"
                "class Invoice(BaseModel):\n    number: str\n"
            },
        )

        assert _edges(self._parse(tmp_path)) == [
            ("Order", "billing.models.address.Address", "address")
        ]
        assert "refers to" not in capsys.readouterr().err

    def test_an_explicit_re_export_next_to_such_a_star(self, tmp_path: Path) -> None:
        self._layout(tmp_path, "from .address import Address\nfrom .invoice import *\n")
        _write(
            tmp_path,
            {
                "billing/models/invoice.py": "from typing import TYPE_CHECKING\n\n"
                "if TYPE_CHECKING:\n    from .address import Address\n"
            },
        )

        assert _edges(self._parse(tmp_path)) == [
            ("Order", "billing.models.address.Address", "address")
        ]

    def test_a_star_from_an_unscanned_module_is_quiet(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._layout(tmp_path, "from somepkg import *\n")

        assert _edges(self._parse(tmp_path)) == []
        assert "refers to" not in capsys.readouterr().err

    def test_a_module_defining_the_name_itself_is_quiet(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._layout(tmp_path, "from .address import *\n\n\nclass Address:\n    pass\n")

        assert _edges(self._parse(tmp_path)) == []
        assert "refers to" not in capsys.readouterr().err

    def test_a_binding_in_an_except_branch_is_reported(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._layout(tmp_path, "from .address import *\nfrom .compat import *\n")
        _write(
            tmp_path,
            {
                "billing/models/compat.py": "try:\n    import fastlib\n"
                "except ImportError:\n    from .legacy import Address\n"
            },
        )

        assert _edges(self._parse(tmp_path)) == []
        assert "orders/models.py refers to 'Address'" in capsys.readouterr().err

    def test_a_re_export_erdify_cannot_follow_is_reported(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._layout(
            tmp_path, "try:\n    from .address import Address\nexcept ImportError:\n    pass\n"
        )

        assert _edges(self._parse(tmp_path)) == []
        assert "orders/models.py refers to 'Address'" in capsys.readouterr().err


def test_two_scanned_modules_reaching_no_candidate_are_quiet(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _packages(tmp_path, "billing", "shipping")
    _write(tmp_path, ADDRESS)
    _write(
        tmp_path,
        {
            "a/utils.py": "VALUE = 1\n",
            "b/utils.py": "VALUE = 2\n",
            "c/models.py": "from pydantic import BaseModel\nfrom utils import Address\n\n\n"
            "class Order(BaseModel):\n    note: str\n\n\n"
            "def make() -> Address:\n    return Address()\n",
        },
    )

    parse_models_directory(tmp_path, include_patterns=["**/*.py"])

    assert "refers to" not in capsys.readouterr().err


def test_a_bare_django_name_is_not_resolved_by_the_files_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Django resolves a bare name only in the model's app label."""
    _packages(tmp_path, "billing", "shipping")
    profile = (
        "from django.db import models\n\n\n"
        "class Profile(models.Model):\n    name = models.CharField(max_length=9)\n"
    )
    _write(
        tmp_path,
        {
            "billing/models.py": profile,
            "shipping/models.py": profile,
            "billing/other.py": "from django.db import models\n\n\n"
            "class Payment(models.Model):\n"
            '    profile = models.ForeignKey("Profile", on_delete=models.CASCADE)\n\n'
            "    class Meta:\n        app_label = 'payments'\n",
        },
    )

    entities, _ = parse_models_directory(tmp_path, include_patterns=["**/*.py"])

    assert _edges(dict(entities)) == []
    assert "billing/other.py refers to 'Profile'" in capsys.readouterr().err


class TestReleaseAudit:
    """Cases the 1.9.0 docs audit found (#367)."""

    @pytest.fixture
    def root(self, tmp_path: Path) -> Path:
        _packages(tmp_path, "billing", "shipping", "orders")
        _write(tmp_path, ADDRESS)
        return tmp_path

    def test_plantuml_titles_namesakes_of_one_table_by_their_name(self, root: Path) -> None:
        entities, _ = parse_models_directory(root)

        plantuml = generate_plantuml(dict(entities))

        assert 'entity "billing.models.Address" as billing_models_Address {' in plantuml
        assert 'entity "shipping.models.Address" as shipping_models_Address {' in plantuml

    def test_a_key_that_cannot_tell_the_namesakes_apart_draws_no_edge(self, root: Path) -> None:
        _write(
            root,
            {
                "orders/models.py": "from pydantic import BaseModel\n\n\n"
                "class Order(BaseModel):\n    id: int\n    address_id: int\n"
            },
        )

        entities, _ = parse_models_directory(root, infer_keys=True)

        # Order is in neither module: which Address is meant can't be told.
        assert _edges(dict(entities)) == []


def test_namesakes_no_module_decides_fall_back_to_a_sql_table_of_the_name() -> None:
    from erdify.config import FieldInfo

    def address(name: str, module: str | None, source: str) -> EntityInfo:
        return EntityInfo(name=name, table_name="address", module=module, source=source)

    fk = FieldInfo("address_id", "int", is_foreign_key=True, foreign_table="address.id")
    entities = {
        "billing.models.Address": address("billing.models.Address", "billing.models", "pydantic"),
        "shipping.models.Address": address(
            "shipping.models.Address", "shipping.models", "pydantic"
        ),
        "address": address("address", None, "sql"),
        "Order": EntityInfo(name="Order", table_name="order", module="orders.models", fields=[fk]),
    }

    assert _edges(entities) == [("Order", "address", "address_id")]
