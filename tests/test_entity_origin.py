"""Where an entity comes from: ``schema``, ``module`` and ``app`` (#358)."""

import json
from pathlib import Path

import pytest

from erdify import generate_json, parse_models_directory
from erdify.parser.common import module_name

HEADER = """\
from sqlalchemy import Column, Integer, MetaData, Table, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column


class Base(DeclarativeBase):
    pass
"""


def _write(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class TestModuleName:
    def test_named_from_the_package_chain(self, tmp_path: Path) -> None:
        _write(tmp_path / "src" / "shop" / "__init__.py")
        _write(tmp_path / "src" / "shop" / "models" / "__init__.py")
        order = _write(tmp_path / "src" / "shop" / "models" / "order.py")

        assert module_name(order) == "shop.models.order"

    def test_package_init_is_the_package(self, tmp_path: Path) -> None:
        _write(tmp_path / "shop" / "__init__.py")
        init = _write(tmp_path / "shop" / "models" / "__init__.py")

        assert module_name(init) == "shop.models"

    def test_file_outside_a_package_is_its_stem(self, tmp_path: Path) -> None:
        assert module_name(_write(tmp_path / "models.py")) == "models"

    def test_does_not_depend_on_how_the_path_is_written(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write(tmp_path / "shop" / "__init__.py")
        _write(tmp_path / "shop" / "models.py")
        monkeypatch.chdir(tmp_path / "shop")

        assert module_name(Path("models.py")) == "shop.models"
        assert module_name(Path("../shop/./models.py")) == "shop.models"


class TestPythonSources:
    def test_module_of_every_python_source(self, tmp_path: Path) -> None:
        _write(tmp_path / "app" / "__init__.py")
        _write(
            tmp_path / "app" / "models.py",
            "from pydantic import BaseModel\n"
            "from dataclasses import dataclass\n\n"
            "class Item(BaseModel):\n    id: int\n\n"
            "@dataclass\nclass Row:\n    id: int\n",
        )

        entities, _ = parse_models_directory(tmp_path)

        assert {(e.name, e.module, e.schema, e.app) for e in entities.values()} == {
            ("Item", "app.models", None, None),
            ("Row", "app.models", None, None),
        }

    def test_core_table_gets_the_module_of_its_file(self, tmp_path: Path) -> None:
        _write(tmp_path / "db" / "__init__.py")
        _write(
            tmp_path / "db" / "models.py",
            HEADER + 'tag = Table("tag", Base.metadata, Column("id", Integer))\n',
        )

        entities, _ = parse_models_directory(tmp_path)

        assert entities["tag"].module == "db.models"

    def test_django_app_label(self, tmp_path: Path) -> None:
        _write(tmp_path / "shop" / "__init__.py")
        _write(
            tmp_path / "shop" / "models.py",
            "from django.db import models\n\n"
            "class Order(models.Model):\n    pass\n\n"
            "class Refund(models.Model):\n"
            "    class Meta:\n        app_label = 'billing'\n",
        )

        entities, _ = parse_models_directory(tmp_path)

        assert (entities["Order"].app, entities["Order"].module) == ("shop", "shop.models")
        assert entities["Refund"].app == "billing"
        assert entities["Order"].schema is None


class TestSqlAlchemySchema:
    def _schema(self, tmp_path: Path, body: str, name: str) -> str | None:
        _write(tmp_path / "models.py", HEADER + body)
        entities, _ = parse_models_directory(tmp_path)
        return entities[name].schema

    def test_declared_attr_table_args_are_read(self, tmp_path: Path) -> None:
        body = """
class Mixin:
    __table_args__ = {"schema": "mix"}


class Item(Mixin, Base):
    __tablename__ = "item"

    @declared_attr.directive
    def __table_args__(cls):
        return {"schema": "dynamic"}

    id: Mapped[int] = mapped_column(primary_key=True)
"""
        assert self._schema(tmp_path, body, "Item") == "dynamic"

    def test_unreadable_declared_attr_table_args_give_no_schema(self, tmp_path: Path) -> None:
        body = """
class Mixin:
    __table_args__ = {"schema": "mix"}


class Item(Mixin, Base):
    __tablename__ = "item"

    @declared_attr.directive
    def __table_args__(cls):
        args = {"schema": "dynamic"}
        return args

    id: Mapped[int] = mapped_column(primary_key=True)
"""
        assert self._schema(tmp_path, body, "Item") is None

    def test_declared_attr_with_a_docstring(self, tmp_path: Path) -> None:
        body = """
class Item(Base):
    __tablename__ = "item"

    @declared_attr.directive
    def __table_args__(cls):
        \"\"\"In the catalog schema.\"\"\"
        return {"schema": "catalog"}

    id: Mapped[int] = mapped_column(primary_key=True)
"""
        assert self._schema(tmp_path, body, "Item") == "catalog"

    def test_core_table_metadata_keyword_and_annotated_variable(self, tmp_path: Path) -> None:
        body = """
md: MetaData = MetaData(schema="audit")
log = Table("log", Column("id", Integer, primary_key=True), metadata=md)
"""
        assert self._schema(tmp_path, body, "log") == "audit"

    def test_metadata_that_is_not_a_metadata_call_gives_none(self, tmp_path: Path) -> None:
        body = """
md = Base.metadata
log = Table("log", md, Column("id", Integer, primary_key=True))
"""
        assert self._schema(tmp_path, body, "log") is None

    def test_table_args_ending_in_a_variable_give_none(self, tmp_path: Path) -> None:
        body = """
TABLE_KW = {"schema": "x"}


class Item(Base):
    __tablename__ = "item"
    __table_args__ = (UniqueConstraint("code"), TABLE_KW)

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str]
"""
        assert self._schema(tmp_path, body, "Item") is None

    def test_mapped_core_table_metadata_is_looked_up_in_the_tables_file(
        self, tmp_path: Path
    ) -> None:
        for name in ("billing", "crm"):
            _write(
                tmp_path / name / "models.py",
                "from sqlalchemy import Column, Integer, MetaData, Table\n"
                f'metadata = MetaData(schema="{name}")\n'
                f'{name}_rows = Table("{name}_rows", metadata, Column("id", Integer))\n',
            )
        body = """
from billing.models import billing_rows


class Invoice(Base):
    __table__ = billing_rows
"""
        assert self._schema(tmp_path, body, "Invoice") == "billing"

    def test_non_literal_schema_gives_none(self, tmp_path: Path) -> None:
        body = """
SCHEMA = "core"


class Item(Base):
    __tablename__ = "item"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(primary_key=True)
"""
        assert self._schema(tmp_path, body, "Item") is None

    def test_metadata_variable_is_looked_up_in_the_tables_file_first(self, tmp_path: Path) -> None:
        _write(
            tmp_path / "other" / "models.py",
            'from sqlalchemy import MetaData\nmd = MetaData(schema="b")\n',
        )
        body = """
md = MetaData(schema="a")
tag = Table("tag", md, Column("id", Integer, primary_key=True))
"""
        assert self._schema(tmp_path, body, "tag") == "a"

    def test_metadata_variable_defined_in_two_other_files_is_ambiguous(
        self, tmp_path: Path
    ) -> None:
        for name in ("a", "b"):
            _write(
                tmp_path / name / "models.py",
                f'from sqlalchemy import MetaData\nmd = MetaData(schema="{name}")\n',
            )
        body = """
tag = Table("tag", md, Column("id", Integer, primary_key=True))
"""
        _write(tmp_path / "models.py", HEADER + body)
        entities, _ = parse_models_directory(tmp_path)
        assert entities["tag"].schema is None


class TestSqlSchema:
    @pytest.fixture(autouse=True)
    def _sqlglot(self) -> None:
        pytest.importorskip("sqlglot")

    def test_schema_qualified_tables(self, tmp_path: Path) -> None:
        sql = _write(
            tmp_path / "schema.sql",
            "CREATE TABLE core.customer (id INT PRIMARY KEY);\n"
            "CREATE TABLE warehouse.mart.sale (id INT PRIMARY KEY);\n"
            "CREATE TABLE plain (id INT PRIMARY KEY);\n",
        )

        entities, _ = parse_models_directory(sql)

        assert {(e.name, e.schema, e.module, e.app) for e in entities.values()} == {
            ("customer", "core", None, None),
            ("sale", "mart", None, None),  # the catalog part is not included
            ("plain", None, None, None),
        }


def test_json_emits_schema_module_and_app(tmp_path: Path) -> None:
    _write(tmp_path / "shop" / "__init__.py")
    _write(
        tmp_path / "shop" / "models.py",
        HEADER
        + """
class Item(Base):
    __tablename__ = "item"
    __table_args__ = {"schema": "sales"}

    id: Mapped[int] = mapped_column(primary_key=True)
""",
    )
    entities, enums = parse_models_directory(tmp_path)

    item = json.loads(generate_json(entities, enums))["entities"][0]

    assert (item["schema"], item["module"], item["app"]) == ("sales", "shop.models", None)
