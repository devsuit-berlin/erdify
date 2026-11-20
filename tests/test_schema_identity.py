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

    def test_a_schema_matching_two_tables_case_insensitively_draws_no_edge(
        self, tmp_path: Path
    ) -> None:
        entities = _sql(
            tmp_path,
            'CREATE TABLE "Core".customer (id INT PRIMARY KEY);\n'
            'CREATE TABLE "CORE".customer (id INT PRIMARY KEY);\n'
            "CREATE TABLE orders (id INT PRIMARY KEY, cid INT REFERENCES core.customer(id));\n",
            "postgres",
        )

        assert _edges(entities) == []

    def test_a_redefined_table_takes_the_foreign_keys_of_its_later_definition(
        self, tmp_path: Path
    ) -> None:
        entities = _sql(
            tmp_path,
            "CREATE TABLE x (id INT PRIMARY KEY);\n"
            "CREATE TABLE y (id INT PRIMARY KEY);\n"
            "CREATE TABLE Customer (a INT REFERENCES x(id));\n"
            "CREATE TABLE CUSTOMER (a INT REFERENCES y(id));\n",
            "postgres",
        )

        assert list(entities) == ["x", "y", "CUSTOMER"]
        assert _fk_targets(entities)["CUSTOMER"] == ["y.id"]

    def test_a_schema_matches_its_table_case_insensitively(self, tmp_path: Path) -> None:
        entities = _sql(
            tmp_path,
            'CREATE TABLE core."Customer" (id INT PRIMARY KEY);\n'
            "CREATE TABLE mart.customer (id INT PRIMARY KEY,"
            " core_id INT REFERENCES core.customer(id));\n",
            "postgres",
        )

        assert _fk_targets(entities)["customer"] == ["core.Customer.id"]

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

    def test_a_bare_name_excludes_the_table_in_every_schema(self, tmp_path: Path) -> None:
        pytest.importorskip("sqlglot")
        path = tmp_path / "schema.sql"
        path.write_text(
            "CREATE TABLE customer (id INT PRIMARY KEY);\n"
            "CREATE TABLE core.customer (id INT PRIMARY KEY);\n",
            encoding="utf-8",
        )

        entities, _ = parse_models_directory(path, exclude_patterns=["customer"])

        assert list(entities) == []

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

    def test_sqlmodel_schema_qualified_foreign_key_draws_its_edge(self, tmp_path: Path) -> None:
        """#373: ``Field(foreign_key="core.customers.id")`` across schemas."""
        (tmp_path / "models.py").write_text(
            """
from sqlmodel import Field, SQLModel


class Customer(SQLModel, table=True):
    __tablename__ = "customers"
    __table_args__ = {"schema": "core"}
    id: int = Field(primary_key=True)


class Invoice(SQLModel, table=True):
    __tablename__ = "invoices"
    __table_args__ = {"schema": "billing"}
    id: int = Field(primary_key=True)
    customer_id: int = Field(foreign_key="core.customers.id")
""",
            encoding="utf-8",
        )

        entities, _ = parse_models_directory(tmp_path)

        assert _edges(dict(entities)) == [("Invoice", "Customer", "customer_id")]

    def test_unqualified_foreign_key_takes_the_metadata_schema(self, tmp_path: Path) -> None:
        """#370: SQLAlchemy resolves it in MetaData(schema=...)'s schema."""
        (tmp_path / "models.py").write_text(
            """
from sqlalchemy import ForeignKey, MetaData
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    metadata = MetaData(schema="core")


class Customer(Base):
    __tablename__ = "customer"
    id: Mapped[int] = mapped_column(primary_key=True)


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = {"schema": "sales"}
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customer.id"))
""",
            encoding="utf-8",
        )

        entities, _ = parse_models_directory(tmp_path)

        # The metadata's schema, not the referencing table's own (sales).
        assert _fk_targets(dict(entities))["Order"] == ["core.customer.id"]
        assert _edges(dict(entities)) == [("Order", "Customer", "customer_id")]

    def test_schema_qualified_target_finds_renamed_key_and_core_type(self, tmp_path: Path) -> None:
        (tmp_path / "models.py").write_text(
            """
from sqlalchemy import BigInteger, Column, ForeignKey, MetaData, Table
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    metadata = MetaData(schema="core")


class Account(Base):
    __tablename__ = "account"
    id: Mapped[int] = mapped_column("account_id", BigInteger, key="id", primary_key=True)


class Payment(Base):
    __tablename__ = "payment"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("core.account.id"))


audit = Table("audit", Base.metadata, Column("account_id", ForeignKey("account.id")))
""",
            encoding="utf-8",
        )

        entities, _ = parse_models_directory(tmp_path)

        # The key "id" is the column "account_id"; the Core column takes its type.
        assert _fk_targets(dict(entities))["Payment"] == ["core.account.account_id"]
        audit = dict(entities)["audit"]
        assert audit.fields[0].foreign_table == "core.account.account_id"
        account_id = dict(entities)["Account"].fields[0]
        assert audit.fields[0].type_str == account_id.type_str != ""

    def test_renamed_key_of_a_same_name_table_in_another_schema(self, tmp_path: Path) -> None:
        (tmp_path / "models.py").write_text(
            SQLALCHEMY_HEADER
            + """

class CoreAccount(Base):
    __tablename__ = "account"
    __table_args__ = {"schema": "core"}
    id: Mapped[int] = mapped_column("account_id", key="id", primary_key=True)


class SalesAccount(Base):
    __tablename__ = "account"
    __table_args__ = {"schema": "sales"}
    id: Mapped[int] = mapped_column(primary_key=True)


class Payment(Base):
    __tablename__ = "payment"
    id: Mapped[int] = mapped_column(primary_key=True)
    core_id: Mapped[int] = mapped_column(ForeignKey("core.account.id"))
    sales_id: Mapped[int] = mapped_column(ForeignKey("sales.account.id"))
""",
            encoding="utf-8",
        )

        entities, _ = parse_models_directory(tmp_path)

        assert _fk_targets(dict(entities))["Payment"] == [
            "core.account.account_id",
            "sales.account.id",
        ]

    def test_a_core_table_on_other_metadata_keeps_its_targets(self, tmp_path: Path) -> None:
        (tmp_path / "models.py").write_text(
            """
from sqlalchemy import Column, ForeignKey, Integer, MetaData, Table
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

other = MetaData()


class Base(DeclarativeBase):
    metadata = MetaData(schema="core")


class Customer(Base):
    __tablename__ = "customer"
    id: Mapped[int] = mapped_column(primary_key=True)


plain_customer = Table("customer", other, Column("id", Integer, primary_key=True))


class Order(Base):
    __table__ = Table(
        "orders",
        other,
        Column("id", Integer, primary_key=True),
        Column("cid", ForeignKey("customer.id")),
    )
""",
            encoding="utf-8",
        )

        entities, _ = parse_models_directory(tmp_path)

        # Resolved in the table's own metadata (no schema), not the class's.
        assert _fk_targets(dict(entities))["Order"] == ["customer.id"]
        assert _edges(dict(entities)) == [("Order", "plain_customer", "cid")]

    def test_single_table_subclass_columns_resolve_in_their_tables_metadata(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "models.py").write_text(
            """
from sqlalchemy import Column, ForeignKey, Integer, MetaData, String, Table
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

other = MetaData()


class Base(DeclarativeBase):
    metadata = MetaData(schema="core")


class Customer(Base):
    __tablename__ = "customer"
    id: Mapped[int] = mapped_column(primary_key=True)


plain_customer = Table("customer", other, Column("id", Integer, primary_key=True))


class Order(Base):
    __table__ = Table(
        "orders",
        other,
        Column("id", Integer, primary_key=True),
        Column("kind", String),
    )
    __mapper_args__ = {"polymorphic_on": "kind"}


class SpecialOrder(Order):
    __mapper_args__ = {"polymorphic_identity": "special"}
    cid: Mapped[int] = mapped_column(ForeignKey("customer.id"), nullable=True)


class Invoice(Base):
    __tablename__ = "invoice"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str]
    __mapper_args__ = {"polymorphic_on": "kind"}


class CreditNote(Invoice):
    __mapper_args__ = {"polymorphic_identity": "credit"}
    customer_id: Mapped[int] = mapped_column(ForeignKey("customer.id"), nullable=True)
""",
            encoding="utf-8",
        )

        entities, _ = parse_models_directory(tmp_path)
        targets = _fk_targets(dict(entities))

        # The Core table's metadata has no schema; the base's has "core".
        assert targets["Order"] == ["customer.id"]
        assert targets["Invoice"] == ["core.customer.id"]

    def test_a_target_whose_schema_is_not_read_keeps_its_edge(self, tmp_path: Path) -> None:
        (tmp_path / "models.py").write_text(
            """
from sqlalchemy import Column, ForeignKey, Integer, MetaData, Table
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    metadata = MetaData(schema="core")


md = Base.metadata
customer = Table("customer", md, Column("id", Integer, primary_key=True))


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customer.id"))
""",
            encoding="utf-8",
        )

        entities, _ = parse_models_directory(tmp_path)

        # erdify can't read `md`'s schema: the target stays as written.
        assert _fk_targets(dict(entities))["Order"] == ["customer.id"]
        assert _edges(dict(entities)) == [("Order", "customer", "customer_id")]

    def test_sqlmodel_picks_the_named_schemas_table(self, tmp_path: Path) -> None:
        (tmp_path / "models.py").write_text(
            """
from sqlmodel import Field, SQLModel


class CoreCustomer(SQLModel, table=True):
    __tablename__ = "customers"
    __table_args__ = {"schema": "core"}
    id: int = Field(primary_key=True)


class BillingCustomer(SQLModel, table=True):
    __tablename__ = "customers"
    __table_args__ = {"schema": "billing"}
    id: int = Field(primary_key=True)
    core_id: int = Field(foreign_key="core.customers.id")
""",
            encoding="utf-8",
        )

        entities, _ = parse_models_directory(tmp_path)

        assert _edges(dict(entities)) == [("BillingCustomer", "CoreCustomer", "core_id")]


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

    def test_sql_reference_into_a_schema_prefers_the_sql_table(self, tmp_path: Path) -> None:
        pytest.importorskip("sqlglot")
        (tmp_path / "models.py").write_text(
            SQLALCHEMY_HEADER
            + """

class Customer(Base):
    __tablename__ = "customer"
    id: Mapped[int] = mapped_column(primary_key=True)
""",
            encoding="utf-8",
        )
        (tmp_path / "schema.sql").write_text(
            "CREATE TABLE public.customer (id INT PRIMARY KEY);\n"
            "CREATE TABLE public.orders (id INT PRIMARY KEY,"
            " cid INT REFERENCES public.customer(id));\n",
            encoding="utf-8",
        )

        entities, _ = parse_models_directory(tmp_path, include_patterns=["models.py", "*.sql"])

        # The table in the schema the reference names, not the Python model.
        assert _edges(dict(entities)) == [("orders", "customer", "cid")]

    def test_sql_reference_to_a_python_models_schema_in_another_case(self, tmp_path: Path) -> None:
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
            "CREATE TABLE orders (id INT PRIMARY KEY, cid INT REFERENCES CORE.customer(id));\n",
            encoding="utf-8",
        )

        entities, _ = parse_models_directory(
            tmp_path, include_patterns=["models.py", "*.sql"], sql_dialect="postgres"
        )

        assert _edges(dict(entities)) == [("orders", "Customer", "cid")]

    def test_sql_reference_to_a_python_model_without_a_schema(self, tmp_path: Path) -> None:
        pytest.importorskip("sqlglot")
        (tmp_path / "models.py").write_text(
            SQLALCHEMY_HEADER
            + """

class Order(Base):
    __tablename__ = "shop_order"
    id: Mapped[int] = mapped_column(primary_key=True)
""",
            encoding="utf-8",
        )
        (tmp_path / "schema.sql").write_text(
            "CREATE TABLE public.invoice (id INT PRIMARY KEY,"
            " order_id INT REFERENCES public.shop_order(id));\n",
            encoding="utf-8",
        )

        entities, _ = parse_models_directory(tmp_path, include_patterns=["models.py", "*.sql"])

        assert _edges(dict(entities)) == [("invoice", "Order", "order_id")]

    def test_one_table_drawn_twice_in_one_schema_keeps_its_edge(self, tmp_path: Path) -> None:
        pytest.importorskip("sqlglot")
        (tmp_path / "models.py").write_text(
            """
from sqlalchemy import ForeignKey, MetaData
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    metadata = MetaData(schema="core")


class Customer(Base):
    __tablename__ = "customer"
    id: Mapped[int] = mapped_column(primary_key=True)


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customer.id"))
""",
            encoding="utf-8",
        )
        (tmp_path / "schema.sql").write_text(
            "CREATE TABLE core.customer (id INT PRIMARY KEY);\n", encoding="utf-8"
        )

        entities, _ = parse_models_directory(tmp_path, include_patterns=["models.py", "*.sql"])

        assert _edges(dict(entities)) == [("Order", "Customer", "customer_id")]


class TestSameNameClasses:
    def test_same_name_models_are_both_drawn(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """#367: no longer one entity; each is named after its module."""
        for package, field in (("billing", "street"), ("shipping", "city")):
            (tmp_path / package).mkdir()
            (tmp_path / package / "models.py").write_text(
                "from pydantic import BaseModel\n\n\n"
                f"class Address(BaseModel):\n    {field}: str\n",
                encoding="utf-8",
            )

        entities, _ = parse_models_directory(tmp_path)

        assert {name: [f.name for f in e.fields] for name, e in entities.items()} == {
            "billing.models.Address": ["street"],
            "shipping.models.Address": ["city"],
        }
        assert "Warning" not in capsys.readouterr().err

    def test_three_definitions_are_three_entities(self, tmp_path: Path) -> None:
        for package in ("a", "b", "c"):
            (tmp_path / package).mkdir()
            (tmp_path / package / "models.py").write_text(
                "from pydantic import BaseModel\n\n\n"
                f"class Address(BaseModel):\n    {package}: str\n",
                encoding="utf-8",
            )

        entities, _ = parse_models_directory(tmp_path)

        assert sorted(entities) == ["a.models.Address", "b.models.Address", "c.models.Address"]

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

    def test_a_model_hidden_by_a_plain_class_is_reported(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / "a").mkdir()
        (tmp_path / "b").mkdir()
        (tmp_path / "a" / "models.py").write_text(
            "from pydantic import BaseModel\n\n\nclass Address(BaseModel):\n    city: str\n",
            encoding="utf-8",
        )
        (tmp_path / "b" / "models.py").write_text("class Address:\n    pass\n", encoding="utf-8")

        entities, _ = parse_models_directory(tmp_path)

        assert list(entities) == []
        err = capsys.readouterr().err
        assert "model class 'Address' in a/models.py is not drawn" in err
        assert "the class of that name in b/models.py, which is not a model, replaces it" in err

    def test_the_class_name_excludes_every_same_name_model(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        for package in ("a", "b"):
            (tmp_path / package).mkdir()
            (tmp_path / package / "models.py").write_text(
                "from pydantic import BaseModel\n\n\nclass Address(BaseModel):\n    city: str\n",
                encoding="utf-8",
            )

        assert parse_models_directory(tmp_path, exclude_patterns=["Address"])[0] == {}
        assert list(parse_models_directory(tmp_path, exclude_patterns=["a.models.*"])[0]) == [
            "b.models.Address"
        ]
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
