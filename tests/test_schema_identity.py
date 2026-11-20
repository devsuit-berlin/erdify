"""Same-name tables in different schemas stay apart (#353)."""

import json
from pathlib import Path

import pytest

from erdify import diagram_edges, generate_json, generate_mermaid, parse_models_directory
from erdify.generator import generate_plantuml


def _sql(tmp_path: Path, text: str, dialect: str | None = None) -> dict[str, object]:
    pytest.importorskip("sqlglot")
    path = tmp_path / "schema.sql"
    path.write_text(text, encoding="utf-8")
    entities, _ = parse_models_directory(path, sql_dialect=dialect)
    return dict(entities)


def _fk_targets(entities: dict[str, object]) -> dict[str, list[str | None]]:
    return {
        name: [f.foreign_table for f in e.fields if f.is_foreign_key]  # type: ignore[attr-defined]
        for name, e in entities.items()
    }


def _edges(entities: dict[str, object]) -> list[tuple[str, str, str]]:
    return [(e.from_entity, e.to_entity, e.label) for e in diagram_edges(entities)]  # type: ignore[arg-type]


ISSUE_REPRO = """
create or replace TABLE CORE.CUSTOMER (ID NUMBER(38,0) NOT NULL, EMAIL VARCHAR, primary key (ID));
create or replace TABLE MART.CUSTOMER (
  ID NUMBER(38,0) NOT NULL, CORE_ID NUMBER(38,0),
  primary key (ID), foreign key (CORE_ID) references CORE.CUSTOMER(ID)
);
"""


class TestSqlTables:
    def test_same_name_tables_in_two_schemas_are_two_entities(self, tmp_path: Path) -> None:
        entities = _sql(tmp_path, ISSUE_REPRO, "snowflake")

        assert {
            name: (e.table_name, e.schema, [f.name for f in e.fields])  # type: ignore[attr-defined]
            for name, e in entities.items()
        } == {
            "CORE.CUSTOMER": ("CUSTOMER", "CORE", ["ID", "EMAIL"]),
            "MART.CUSTOMER": ("CUSTOMER", "MART", ["ID", "CORE_ID"]),
        }
        assert _fk_targets(entities)["MART.CUSTOMER"] == ["CORE.CUSTOMER.ID"]
        assert _edges(entities) == [("MART.CUSTOMER", "CORE.CUSTOMER", "CORE_ID")]

    def test_a_name_in_one_schema_only_stays_short(self, tmp_path: Path) -> None:
        entities = _sql(
            tmp_path,
            "CREATE TABLE core.customer (id INT PRIMARY KEY);\n"
            "CREATE TABLE mart.sale (id INT PRIMARY KEY,"
            " customer_id INT REFERENCES core.customer(id));\n",
        )

        assert list(entities) == ["customer", "sale"]
        assert _fk_targets(entities)["sale"] == ["core.customer.id"]
        assert _edges(entities) == [("sale", "customer", "customer_id")]

    def test_a_table_without_a_schema_keeps_the_short_name(self, tmp_path: Path) -> None:
        entities = _sql(
            tmp_path,
            "CREATE TABLE customer (id INT PRIMARY KEY);\n"
            "CREATE TABLE mart.customer (id INT PRIMARY KEY);\n"
            "CREATE TABLE core.sale (id INT PRIMARY KEY,"
            " customer_id INT REFERENCES customer(id));\n",
        )

        assert list(entities) == ["customer", "mart.customer", "sale"]
        # core has no customer to prefer: the one without a schema.
        assert _fk_targets(entities)["sale"] == ["customer.id"]
        assert _edges(entities) == [("sale", "customer", "customer_id")]

    def test_unqualified_reference_prefers_the_referencing_tables_schema(
        self, tmp_path: Path
    ) -> None:
        entities = _sql(
            tmp_path,
            "CREATE TABLE core.customer (id INT PRIMARY KEY);\n"
            "CREATE TABLE mart.customer (id INT PRIMARY KEY);\n"
            "CREATE TABLE mart.sale (id INT PRIMARY KEY,"
            " customer_id INT REFERENCES customer(id));\n",
        )

        assert _fk_targets(entities)["sale"] == ["mart.customer.id"]
        assert _edges(entities) == [("sale", "mart.customer", "customer_id")]

    def test_a_schema_finds_the_only_table_of_that_name(self, tmp_path: Path) -> None:
        entities = _sql(
            tmp_path,
            "CREATE TABLE customer (id INT PRIMARY KEY);\n"
            "CREATE TABLE sale (id INT PRIMARY KEY,"
            " customer_id INT REFERENCES public.customer(id));\n",
        )

        # As before schemas were told apart: the only customer table.
        assert _fk_targets(entities)["sale"] == ["customer.id"]
        assert _edges(entities) == [("sale", "customer", "customer_id")]

    def test_a_schema_never_finds_a_table_in_another_schema(self, tmp_path: Path) -> None:
        entities = _sql(
            tmp_path,
            "CREATE TABLE mart.customer (id INT PRIMARY KEY,"
            " core_id INT REFERENCES core.customer(id));\n",
        )

        # core.customer is not in the scan: kept as written, no self-reference.
        assert _fk_targets(entities)["customer"] == ["core.customer.id"]
        assert _edges(entities) == []

    def test_ambiguous_unqualified_reference_draws_no_edge(self, tmp_path: Path) -> None:
        entities = _sql(
            tmp_path,
            "CREATE TABLE core.customer (id INT PRIMARY KEY);\n"
            "CREATE TABLE mart.customer (id INT PRIMARY KEY);\n"
            "CREATE TABLE sale (id INT PRIMARY KEY, customer_id INT REFERENCES customer(id));\n",
        )

        assert _fk_targets(entities)["sale"] == ["customer.id"]
        assert _edges(entities) == []

    def test_schema_and_table_fold_like_the_dialect(self, tmp_path: Path) -> None:
        entities = _sql(
            tmp_path,
            "CREATE TABLE core.customer (id INT PRIMARY KEY);\n"
            "CREATE TABLE mart.customer (id INT PRIMARY KEY);\n"
            "CREATE TABLE mart.sale (id INT PRIMARY KEY,"
            " customer_id INT REFERENCES CORE.CUSTOMER(ID));\n",
            "postgres",
        )

        assert _fk_targets(entities)["sale"] == ["core.customer.id"]

    def test_quoted_schemas_stay_apart_in_postgres(self, tmp_path: Path) -> None:
        entities = _sql(
            tmp_path,
            'CREATE TABLE "Core".customer (id INT PRIMARY KEY);\n'
            "CREATE TABLE core.customer (id INT PRIMARY KEY);\n",
            "postgres",
        )

        assert list(entities) == ["Core.customer", "core.customer"]

    def test_redefining_a_table_in_the_same_schema_replaces_it(self, tmp_path: Path) -> None:
        entities = _sql(
            tmp_path,
            "CREATE TABLE core.customer (id INT PRIMARY KEY);\n"
            "CREATE OR REPLACE TABLE CORE.CUSTOMER (id INT PRIMARY KEY, email TEXT);\n",
            "snowflake",
        )

        assert [f.name for f in entities["CUSTOMER"].fields] == ["id", "email"]  # type: ignore[attr-defined]
        assert len(entities) == 1

    def test_alter_table_and_index_find_the_schemas_table(self, tmp_path: Path) -> None:
        entities = _sql(
            tmp_path,
            "CREATE TABLE core.customer (id INT PRIMARY KEY, code TEXT);\n"
            "CREATE TABLE mart.customer (id INT PRIMARY KEY, code TEXT, core_id INT);\n"
            "ALTER TABLE mart.customer ADD CONSTRAINT fk FOREIGN KEY (core_id)"
            " REFERENCES core.customer(id);\n"
            "CREATE UNIQUE INDEX ix ON core.customer (code);\n",
            "postgres",
        )

        core, mart = entities["core.customer"], entities["mart.customer"]
        assert [f.name for f in core.fields if f.is_unique] == ["code"]  # type: ignore[attr-defined]
        assert [f.name for f in mart.fields if f.is_unique] == []  # type: ignore[attr-defined]
        assert _fk_targets(entities)["mart.customer"] == ["core.customer.id"]

    def test_names_collide_as_the_dialect_folds_them(self, tmp_path: Path) -> None:
        entities = _sql(
            tmp_path,
            "CREATE TABLE core.customer (id INT PRIMARY KEY);\n"
            "CREATE TABLE MART.CUSTOMER (id INT PRIMARY KEY);\n",
            "snowflake",
        )

        assert list(entities) == ["core.customer", "MART.CUSTOMER"]

    def test_names_that_collide_only_as_written_stay_apart(self, tmp_path: Path) -> None:
        entities = _sql(
            tmp_path,
            'CREATE TABLE core."Customer" (id INT PRIMARY KEY);\n'
            "CREATE TABLE mart.Customer (id INT PRIMARY KEY,"
            ' core_id INT REFERENCES core."Customer"(id));\n',
            "postgres",
        )

        assert list(entities) == ["core.Customer", "mart.Customer"]
        assert _edges(entities) == [("mart.Customer", "core.Customer", "core_id")]

    def test_an_excluded_target_draws_no_edge_to_another_table(self, tmp_path: Path) -> None:
        pytest.importorskip("sqlglot")
        path = tmp_path / "schema.sql"
        path.write_text(
            "CREATE TABLE customer (id INT PRIMARY KEY);\n"
            "CREATE TABLE core.customer (id INT PRIMARY KEY);\n"
            "CREATE TABLE core.orders (id INT PRIMARY KEY,"
            " customer_id INT REFERENCES core.customer(id));\n",
            encoding="utf-8",
        )

        entities, _ = parse_models_directory(path, exclude_patterns=["core.customer"])

        assert list(entities) == ["customer", "orders"]
        assert _edges(dict(entities)) == []

    def test_names_that_still_collide_are_reported(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        entities = _sql(
            tmp_path,
            'CREATE TABLE core."Customer" (id INT PRIMARY KEY);\n'
            "CREATE TABLE core.Customer (id INT PRIMARY KEY, email TEXT);\n",
            "postgres",
        )

        assert list(entities) == ["core.Customer"]
        assert "2 SQL tables are named 'core.Customer'" in capsys.readouterr().err

    def test_a_qualified_name_can_be_excluded(self, tmp_path: Path) -> None:
        pytest.importorskip("sqlglot")
        path = tmp_path / "schema.sql"
        path.write_text(ISSUE_REPRO, encoding="utf-8")

        entities, _ = parse_models_directory(
            path, sql_dialect="snowflake", exclude_patterns=["MART.*"]
        )

        assert list(entities) == ["CORE.CUSTOMER"]
        assert 'entity "CORE.CUSTOMER" as CORE_CUSTOMER' in generate_plantuml(entities)

    def test_link_table_between_same_name_tables(self, tmp_path: Path) -> None:
        entities = _sql(
            tmp_path,
            "CREATE TABLE core.tag (id INT PRIMARY KEY);\n"
            "CREATE TABLE mart.tag (id INT PRIMARY KEY);\n"
            "CREATE TABLE tag_map (core_id INT REFERENCES core.tag(id),"
            " mart_id INT REFERENCES mart.tag(id), PRIMARY KEY (core_id, mart_id));\n",
        )

        assert _edges(entities) == [
            ("core.tag", "tag_map", "core_id"),
            ("tag_map", "mart.tag", "mart_id"),
        ]


class TestRendering:
    def test_diagrams_name_both_tables_with_their_schema(self, tmp_path: Path) -> None:
        entities = _sql(tmp_path, ISSUE_REPRO, "snowflake")

        plantuml = generate_plantuml(entities)  # type: ignore[arg-type]
        assert 'entity "CORE.CUSTOMER" as CORE_CUSTOMER {' in plantuml
        assert 'entity "MART.CUSTOMER" as MART_CUSTOMER {' in plantuml
        assert 'MART_CUSTOMER }o--o| CORE_CUSTOMER : "CORE_ID"' in plantuml
        mermaid = generate_mermaid(entities)  # type: ignore[arg-type]
        assert '"MART.CUSTOMER" }o--o| "CORE.CUSTOMER" : "CORE_ID"' in mermaid

    def test_json_keeps_table_name_and_schema_apart(self, tmp_path: Path) -> None:
        entities = _sql(tmp_path, ISSUE_REPRO, "snowflake")

        doc = json.loads(generate_json(entities))  # type: ignore[arg-type]

        assert [(e["name"], e["schema"], e["table_name"]) for e in doc["entities"]] == [
            ("CORE.CUSTOMER", "CORE", "CUSTOMER"),
            ("MART.CUSTOMER", "MART", "CUSTOMER"),
        ]
        assert [(e["from_entity"], e["to_entity"]) for e in doc["edges"]] == [
            ("MART.CUSTOMER", "CORE.CUSTOMER")
        ]


SQLALCHEMY_HEADER = """
from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass
"""


class TestSqlAlchemy:
    def test_schema_qualified_foreign_key_draws_its_edge(self, tmp_path: Path) -> None:
        (tmp_path / "models.py").write_text(
            SQLALCHEMY_HEADER
            + """

class Customer(Base):
    __tablename__ = "customer"
    __table_args__ = {"schema": "core"}
    id: Mapped[int] = mapped_column(primary_key=True)


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("core.customer.id"))
""",
            encoding="utf-8",
        )

        entities, _ = parse_models_directory(tmp_path)

        assert _edges(dict(entities)) == [("Order", "Customer", "customer_id")]

    def test_foreign_key_resolves_to_the_named_schemas_table(self, tmp_path: Path) -> None:
        (tmp_path / "models.py").write_text(
            SQLALCHEMY_HEADER
            + """

class CoreCustomer(Base):
    __tablename__ = "customer"
    __table_args__ = {"schema": "core"}
    id: Mapped[int] = mapped_column(primary_key=True)


class MartCustomer(Base):
    __tablename__ = "customer"
    __table_args__ = {"schema": "mart"}
    id: Mapped[int] = mapped_column(primary_key=True)
    core_id: Mapped[int] = mapped_column(ForeignKey("core.customer.id"))
""",
            encoding="utf-8",
        )

        entities, _ = parse_models_directory(tmp_path)

        assert _edges(dict(entities)) == [("MartCustomer", "CoreCustomer", "core_id")]
        plantuml = generate_plantuml(dict(entities))
        assert 'entity "core.customer" as CoreCustomer {' in plantuml
        assert 'entity "mart.customer" as MartCustomer {' in plantuml

    def test_foreign_key_to_a_schema_not_scanned_draws_no_edge(self, tmp_path: Path) -> None:
        (tmp_path / "models.py").write_text(
            SQLALCHEMY_HEADER
            + """

class MartCustomer(Base):
    __tablename__ = "customer"
    __table_args__ = {"schema": "mart"}
    id: Mapped[int] = mapped_column(primary_key=True)
    core_id: Mapped[int] = mapped_column(ForeignKey("core.customer.id"))
""",
            encoding="utf-8",
        )

        entities, _ = parse_models_directory(tmp_path)

        assert _edges(dict(entities)) == []

    def test_unqualified_foreign_key_prefers_the_table_without_a_schema(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "models.py").write_text(
            SQLALCHEMY_HEADER
            + """

class Customer(Base):
    __tablename__ = "customer"
    id: Mapped[int] = mapped_column(primary_key=True)


class CoreCustomer(Base):
    __tablename__ = "customer"
    __table_args__ = {"schema": "core"}
    id: Mapped[int] = mapped_column(primary_key=True)
    base_id: Mapped[int] = mapped_column(ForeignKey("customer.id"))
""",
            encoding="utf-8",
        )

        entities, _ = parse_models_directory(tmp_path)

        # SQLAlchemy resolves an unqualified "customer" to the default schema.
        assert _edges(dict(entities)) == [("CoreCustomer", "Customer", "base_id")]


class TestMixedSources:
    def test_python_model_and_sql_table_of_one_name_keep_their_edge(self, tmp_path: Path) -> None:
        pytest.importorskip("sqlglot")
        (tmp_path / "models.py").write_text(
            SQLALCHEMY_HEADER
            + """

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)


class Post(Base):
    __tablename__ = "posts"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
""",
            encoding="utf-8",
        )
        (tmp_path / "schema.sql").write_text(
            "CREATE TABLE users (id INT PRIMARY KEY);\n", encoding="utf-8"
        )

        entities, _ = parse_models_directory(tmp_path, include_patterns=["models.py", "*.sql"])

        assert set(entities) == {"User", "Post", "users"}
        assert _edges(dict(entities)) == [("Post", "User", "user_id")]

    def test_python_model_and_sql_table_in_one_schema_keep_their_edge(self, tmp_path: Path) -> None:
        pytest.importorskip("sqlglot")
        (tmp_path / "models.py").write_text(
            SQLALCHEMY_HEADER
            + """

class Customer(Base):
    __tablename__ = "customer"
    __table_args__ = {"schema": "core"}
    id: Mapped[int] = mapped_column(primary_key=True)
""",
            encoding="utf-8",
        )
        (tmp_path / "schema.sql").write_text(
            "CREATE TABLE core.customer (id INT PRIMARY KEY);\n"
            "CREATE TABLE core.orders (id INT PRIMARY KEY,"
            " customer_id INT REFERENCES core.customer(id));\n",
            encoding="utf-8",
        )

        entities, _ = parse_models_directory(tmp_path, include_patterns=["models.py", "*.sql"])

        assert _edges(dict(entities)) == [("orders", "Customer", "customer_id")]
        # One schema: the table name alone tells them apart.
        plantuml = generate_plantuml(dict(entities))
        assert 'entity "customer" as Customer {' in plantuml
        assert 'entity "customer" as customer {' in plantuml


class TestSameNameClasses:
    def test_a_hidden_model_is_reported(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        for package, field in (("billing", "street"), ("shipping", "city")):
            (tmp_path / package).mkdir()
            (tmp_path / package / "models.py").write_text(
                "from pydantic import BaseModel\n\n\n"
                f"class Address(BaseModel):\n    {field}: str\n",
                encoding="utf-8",
            )

        entities, _ = parse_models_directory(tmp_path)

        assert list(entities) == ["Address"]
        err = capsys.readouterr().err
        assert "model class 'Address' is defined in billing/models.py and in" in err
        assert "only the one in shipping/models.py is drawn" in err

    def test_three_definitions_name_the_one_drawn(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        for package in ("a", "b", "c"):
            (tmp_path / package).mkdir()
            (tmp_path / package / "models.py").write_text(
                "from pydantic import BaseModel\n\n\n"
                f"class Address(BaseModel):\n    {package}: str\n",
                encoding="utf-8",
            )

        entities, _ = parse_models_directory(tmp_path)

        assert [f.name for f in entities["Address"].fields] == ["c"]
        err = capsys.readouterr().err
        assert err.count("Warning") == 1
        assert "defined in a/models.py, b/models.py and in c/models.py" in err
        assert "only the one in c/models.py is drawn" in err

    def test_a_hidden_class_of_a_filtered_source_is_not_reported(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / "a").mkdir()
        (tmp_path / "b").mkdir()
        (tmp_path / "a" / "models.py").write_text(
            "from pydantic import BaseModel\n\n\nclass Address(BaseModel):\n    city: str\n",
            encoding="utf-8",
        )
        (tmp_path / "b" / "models.py").write_text(
            "from dataclasses import dataclass\n\n\n@dataclass\nclass Address:\n    city: str\n",
            encoding="utf-8",
        )

        parse_models_directory(tmp_path, sources=["dataclass"])

        assert "Warning" not in capsys.readouterr().err

    def test_an_excluded_class_is_not_reported(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        for package in ("a", "b"):
            (tmp_path / package).mkdir()
            (tmp_path / package / "models.py").write_text(
                "from pydantic import BaseModel\n\n\nclass Address(BaseModel):\n    city: str\n",
                encoding="utf-8",
            )

        parse_models_directory(tmp_path, exclude_patterns=["Address"])

        assert "Warning" not in capsys.readouterr().err

    def test_a_table_model_extending_its_namesake_is_not_reported(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / "base").mkdir()
        (tmp_path / "app").mkdir()
        (tmp_path / "base" / "models.py").write_text(
            SQLALCHEMY_HEADER
            + """

class Item(Base):
    __tablename__ = "item"
    id: Mapped[int] = mapped_column(primary_key=True)
""",
            encoding="utf-8",
        )
        (tmp_path / "app" / "models.py").write_text(
            """from base.models import Item


class Item(Item):
    __tablename__ = "special_item"
""",
            encoding="utf-8",
        )

        parse_models_directory(tmp_path)

        assert "Warning" not in capsys.readouterr().err

    def test_a_same_name_class_that_is_no_model_is_not_reported(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / "a").mkdir()
        (tmp_path / "b").mkdir()
        (tmp_path / "a" / "models.py").write_text("class Address:\n    pass\n", encoding="utf-8")
        (tmp_path / "b" / "models.py").write_text(
            "from pydantic import BaseModel\n\n\nclass Address(BaseModel):\n    city: str\n",
            encoding="utf-8",
        )

        parse_models_directory(tmp_path)

        assert "Warning" not in capsys.readouterr().err
