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
