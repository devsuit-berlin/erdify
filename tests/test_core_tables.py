"""SQLAlchemy Core tables and classes mapped to them (#297, #305, #306)."""

from pathlib import Path

from erdify.config import EntityInfo, FieldInfo
from erdify.generator import PlantUMLGenerator
from erdify.parser import parse_models_directory

CATALOG = Path(__file__).parent / "fixtures" / "sqlalchemy_edge_cases"


ORM_FOR_DOMAIN_MODULE = """\
from sqlalchemy import Column, ForeignKey, Integer, String, Table
from sqlalchemy.orm import registry, relationship

import model

mapper_registry = registry()

customers = Table(
    "customer", mapper_registry.metadata,
    Column("id", Integer, primary_key=True),
    Column("email", String(100), nullable=False),
)
orders = Table(
    "purchase", mapper_registry.metadata,
    Column("id", Integer, primary_key=True),
    Column("customer_id", ForeignKey("customer.id"), nullable=False),
)


def start_mappers() -> None:
    mapper_registry.map_imperatively(
        model.Customer,
        customers,
        properties={"orders": relationship(model.Order, back_populates="customer")},
    )
    mapper_registry.map_imperatively(
        class_=model.Order,
        local_table=orders,
        properties={"customer": relationship(model.Customer, back_populates="orders")},
    )
"""

AMBIGUOUS_TABLE_IMPORT = """\
from sqlalchemy.orm import DeclarativeBase

from crm import users


class Base(DeclarativeBase):
    pass


class User(Base):
    __table__ = users
"""


def _parse(tmp_path: Path, source: str) -> dict[str, EntityInfo]:
    (tmp_path / "models.py").write_text(source, encoding="utf-8")
    entities, _ = parse_models_directory(tmp_path)
    return entities


def _columns(entity: EntityInfo) -> dict[str, FieldInfo]:
    return {f.name: f for f in entity.fields}


class TestCoreTables:
    """Every module-level Core ``Table(...)`` is a table of the schema (#305)."""

    def test_lookup_and_payload_tables_are_drawn(self) -> None:
        entities, _ = parse_models_directory(CATALOG / "core_tables.py")

        assert set(entities) == {"Account", "account_role", "role", "country", "audit_log"}
        assert entities["account_role"].is_link_table
        assert not entities["audit_log"].is_link_table
        assert entities["country"].table_name == "country"

    def test_foreign_keys_to_a_core_table_draw_an_edge(self) -> None:
        entities, enums = parse_models_directory(CATALOG / "core_tables.py")
        output = PlantUMLGenerator(entities, enums).generate()

        assert 'Account }o--|| country : "country_code"' in output
        assert 'audit_log }o--o| Account : "account_id"' in output

    def test_columns_are_nullable_unless_primary_key_or_not_null(self, tmp_path: Path) -> None:
        entities = _parse(
            tmp_path,
            "from sqlalchemy import Column, Integer, MetaData, String, Table\n\n"
            "metadata = MetaData()\n\n"
            "note = Table(\n"
            "    'note', metadata,\n"
            "    Column('id', Integer, primary_key=True, nullable=True),\n"
            "    Column('title', String(50), nullable=False),\n"
            "    Column('body', String(500)),\n"
            ")\n",
        )

        columns = _columns(entities["note"])
        assert not columns["id"].is_nullable
        assert not columns["title"].is_nullable
        assert columns["body"].is_nullable

    def test_column_types_map_to_python_types(self, tmp_path: Path) -> None:
        entities = _parse(
            tmp_path,
            "import enum\n\n"
            "import sqlalchemy as sa\n"
            "from sqlalchemy.dialects import postgresql\n\n"
            "class Status(enum.Enum):\n    OPEN = 'open'\n\n"
            "metadata = sa.MetaData()\n\n"
            "ticket = sa.Table(\n"
            "    'ticket', metadata,\n"
            "    sa.Column('id', sa.BigInteger, sa.Identity(), primary_key=True),\n"
            "    sa.Column('status', sa.Enum(Status), default=Status.OPEN),\n"
            "    sa.Column('opened', sa.DateTime(timezone=True)),\n"
            "    sa.Column('tags', postgresql.ARRAY(sa.String)),\n"
            "    sa.Column('priority', sa.Integer, default=3),\n"
            "    sa.Column('state', sa.Enum('open', 'closed', name='state')),\n"
            "    sa.Column('ref', sa.Uuid(as_uuid=False)),\n"
            "    sa.Column('ratio', sa.Numeric(10, 2, asdecimal=False)),\n"
            "    sa.Column('score', sa.Float(asdecimal=True)),\n"
            ")\n",
        )

        columns = _columns(entities["ticket"])
        assert columns["id"].type_str == "int"
        assert columns["status"].type_str == "Status"
        assert columns["status"].default_value == "Status.OPEN"
        assert columns["opened"].type_str == "datetime"
        assert columns["tags"].type_str == "ARRAY"
        assert columns["priority"].default_value == "3"
        assert columns["state"].type_str == "str"
        assert columns["ref"].type_str == "str"
        assert columns["ratio"].type_str == "float"
        assert columns["score"].type_str == "Decimal"

    def test_foreign_key_only_column_takes_the_referenced_type(self) -> None:
        entities, _ = parse_models_directory(CATALOG / "core_tables.py")

        assert _columns(entities["audit_log"])["account_id"].type_str == "int"
        assert _columns(entities["account_role"])["role_id"].type_str == "int"

    def test_table_level_constraints(self) -> None:
        entities, _ = parse_models_directory(CATALOG / "core_table_options.py")

        edition = _columns(entities["edition"])
        assert edition["book_id"].is_primary_key and edition["number"].is_primary_key
        assert edition["book_id"].foreign_table == "book.id"
        assert edition["isbn"].is_unique
        review = _columns(entities["review"])
        assert review["edition_book"].is_unique  # UniqueConstraint("eb"): by key
        assert not review["edition_number"].is_unique  # only in a composite one
        assert _columns(entities["tag"])["id"].is_primary_key  # Column(name="id")

    def test_keyword_only_columns_and_annotated_variables(self) -> None:
        entities, _ = parse_models_directory(CATALOG / "core_table_options.py")

        columns = _columns(entities["keyword_only"])
        assert columns["id"].is_primary_key and columns["id"].type_str == "int"
        assert columns["label"].type_str == "str" and not columns["label"].is_nullable

    def test_constraint_with_link_to_name_targets_the_named_column(self) -> None:
        entities, _ = parse_models_directory(CATALOG / "core_table_options.py")

        assert _columns(entities["code_use"])["code_pk"].foreign_table == "code.pk"

    def test_foreign_key_through_a_column_key_names_the_column(self) -> None:
        entities, _ = parse_models_directory(CATALOG / "core_table_options.py")

        assert _columns(entities["office"])["region"].foreign_table == "region.region_id"

    def test_foreign_key_type_comes_from_the_same_metadata(self, tmp_path: Path) -> None:
        """A SQLModel ``user`` table does not type a SQLAlchemy Core foreign key."""
        (tmp_path / "accounts.py").write_text(
            "from sqlmodel import Field, SQLModel\n\n"
            "class User(SQLModel, table=True):\n"
            "    __tablename__ = 'user'\n"
            "    id: str = Field(primary_key=True)\n",
            encoding="utf-8",
        )
        (tmp_path / "audit.py").write_text(
            "from sqlalchemy import Column, ForeignKey, Integer, MetaData, Table\n\n"
            "metadata = MetaData()\n\n"
            "user = Table('user', metadata, Column('id', Integer, primary_key=True))\n"
            "login = Table(\n"
            "    'login', metadata,\n"
            "    Column('id', Integer, primary_key=True),\n"
            "    Column('user_id', ForeignKey('user.id')),\n"
            ")\n",
            encoding="utf-8",
        )
        entities, _ = parse_models_directory(tmp_path, include_patterns=["*.py"])

        assert _columns(entities["login"])["user_id"].type_str == "int"

    def test_same_table_in_two_metadata_collections_gives_no_type(self, tmp_path: Path) -> None:
        for name, kind in (("billing", "Integer"), ("crm", "String(36)")):
            (tmp_path / f"{name}.py").write_text(
                "from sqlalchemy import Column, Integer, MetaData, String, Table\n\n"
                "metadata = MetaData()\n\n"
                f"{name}_user = Table('user', metadata, Column('id', {kind}, primary_key=True))\n",
                encoding="utf-8",
            )
        (tmp_path / "audit.py").write_text(
            "from sqlalchemy import Column, ForeignKey, Integer, MetaData, Table\n\n"
            "metadata = MetaData()\n\n"
            "login = Table(\n"
            "    'login', metadata,\n"
            "    Column('id', Integer, primary_key=True),\n"
            "    Column('user_id', ForeignKey('user.id')),\n"
            ")\n",
            encoding="utf-8",
        )
        entities, _ = parse_models_directory(tmp_path, include_patterns=["*.py"])

        assert _columns(entities["login"])["user_id"].type_str == ""

    def test_a_table_call_without_columns_is_not_drawn(self, tmp_path: Path) -> None:
        entities = _parse(
            tmp_path,
            "from rich.table import Column, Table\n\n"
            "summary = Table('Totals', Column('Age'))\n"
            "plain = Table(Column('Name'))\n",
        )

        assert entities == {}


class TestDeclarativeWithImperativeTable:
    """``__table__ = Table(...)`` maps a declarative class to a Core table (#297)."""

    def test_class_is_drawn_with_the_table_columns(self) -> None:
        entities, _ = parse_models_directory(CATALOG / "imperative_table.py")

        bin_ = entities["Bin"]
        assert bin_.table_name == "bin"
        assert bin_.source == "sqlalchemy"
        assert [f.name for f in bin_.fields] == ["id", "label", "warehouse_id"]
        assert _columns(bin_)["warehouse_id"].foreign_table == "warehouse.id"

    def test_table_variable_is_drawn_once_under_the_class(self) -> None:
        entities, _ = parse_models_directory(CATALOG / "core_table_options.py")

        assert "Shelf" in entities
        assert "shelf_table" not in entities
        assert entities["Book"].table_name == "book"  # __table__: Table = Table(...)
        assert entities["Shelf"].relationships == [("Book", "many", "books")]


class TestMapImperatively:
    """``registry.map_imperatively(Class, table)`` (#306)."""

    def test_classes_from_a_domain_module(self, tmp_path: Path) -> None:
        """``map_imperatively(model.Customer, ...)``: the domain model stays plain."""
        (tmp_path / "model.py").write_text(
            "from dataclasses import dataclass, field\n\n"
            "@dataclass\nclass Customer:\n    email: str\n\n"
            "@dataclass\nclass Order:\n    total: int\n",
            encoding="utf-8",
        )
        (tmp_path / "orm.py").write_text(ORM_FOR_DOMAIN_MODULE, encoding="utf-8")
        entities, _ = parse_models_directory(tmp_path, include_patterns=["*.py"])

        assert set(entities) == {"Customer", "Order"}
        assert entities["Customer"].source == "sqlalchemy"
        assert entities["Customer"].relationships == [("Order", "many", "orders")]
        assert entities["Order"].relationships == [("Customer", "one", "customer")]
        assert entities["Order"].inverse_relationships == {"customer": "orders"}

    def test_table_variable_defined_in_several_files_is_not_guessed(self, tmp_path: Path) -> None:
        for app in ("billing", "crm"):
            (tmp_path / f"{app}.py").write_text(
                "from sqlalchemy import Column, Integer, MetaData, Table\n\n"
                "metadata = MetaData()\n\n"
                f"users = Table('{app}_user', metadata, Column('id', Integer, primary_key=True))\n",
                encoding="utf-8",
            )
        (tmp_path / "models.py").write_text(AMBIGUOUS_TABLE_IMPORT, encoding="utf-8")
        entities, _ = parse_models_directory(tmp_path, include_patterns=["*.py"])

        # Which of the two tables `users` names is unknown: no columns are guessed.
        assert "User" not in entities

    def test_self_reference_optionality_uses_its_own_foreign_key(self, tmp_path: Path) -> None:
        entities = _parse(
            tmp_path,
            "from sqlalchemy import Column, ForeignKey, Integer, Table\n"
            "from sqlalchemy.orm import registry, relationship\n\n"
            "reg = registry()\n\n"
            "owner = Table('owner', reg.metadata, Column('id', Integer, primary_key=True))\n"
            "category = Table(\n"
            "    'category', reg.metadata,\n"
            "    Column('id', Integer, primary_key=True),\n"
            "    Column('parent_id', ForeignKey('category.id'), nullable=False),\n"
            "    Column('owner_id', ForeignKey('owner.id')),\n"
            ")\n\n"
            "class Category:\n    pass\n\n"
            "reg.map_imperatively(\n"
            "    Category, category,\n"
            "    properties={'parent': relationship(Category, remote_side=[category.c.id])},\n"
            ")\n",
        )

        assert entities["Category"].relationships == [("Category", "one", "parent")]
        assert entities["Category"].nullable_relationships == []

    def test_classes_are_named_after_the_mapped_class(self) -> None:
        entities, _ = parse_models_directory(CATALOG / "map_imperatively.py")

        assert set(entities) == {"Team", "Member"}
        assert entities["Member"].table_name == "member"
        assert entities["Member"].relationships == [("Team", "one", "team")]

    def test_mapped_dataclass_is_a_sqlalchemy_entity(self) -> None:
        entities, _ = parse_models_directory(
            CATALOG / "map_imperatively_relationships.py", sources=["sqlalchemy"]
        )

        assert entities["Customer"].source == "sqlalchemy"
        # The table's columns, not the dataclass fields.
        assert [f.name for f in entities["Customer"].fields] == ["id", "email"]
        assert entities["Order"].table_name == "purchase_order"

    def test_relationship_directions_are_inferred(self) -> None:
        entities, _ = parse_models_directory(CATALOG / "map_imperatively_relationships.py")

        customer, order = entities["Customer"], entities["Order"]
        assert customer.relationships == [
            ("Order", "many", "orders"),
            ("Profile", "one", "profile"),
        ]
        assert customer.nullable_relationships == ["profile"]
        assert customer.inverse_relationships == {"orders": "customer", "profile": "customer"}
        assert order.relationships == [
            ("Customer", "one", "customer"),
            ("Customer", "many", "customers"),
            ("Order", "one", "parent"),
            ("Order", "many", "children"),
        ]
        assert set(order.nullable_relationships) == {"customer", "parent"}

    def test_only_relationships_and_own_tables_are_read(self, tmp_path: Path) -> None:
        """column_property() is no relationship; a single-table subclass has no table."""
        entities = _parse(
            tmp_path,
            "from sqlalchemy import Column, ForeignKey, Integer, String, Table\n"
            "from sqlalchemy.orm import column_property, registry, relationship\n\n"
            "reg = registry()\n\n"
            "person = Table(\n"
            "    'person', reg.metadata,\n"
            "    Column('id', Integer, primary_key=True),\n"
            "    Column('kind', String(20)),\n"
            "    Column('first', String(20)),\n"
            ")\n"
            "pet = Table(\n"
            "    'pet', reg.metadata,\n"
            "    Column('id', Integer, primary_key=True),\n"
            "    Column('owner_id', ForeignKey('person.id')),\n"
            ")\n\n"
            "class Person:\n    pass\n\n"
            "class Employee(Person):\n    pass\n\n"
            "class Pet:\n    pass\n\n"
            "reg.map_imperatively(\n"
            "    Person, person, polymorphic_on=person.c.kind, polymorphic_identity='person',\n"
            "    properties={\n"
            "        'display': column_property(person.c.first),\n"
            "        'pets': relationship(argument='Pet'),\n"
            "    },\n"
            ")\n"
            "reg.map_imperatively(Employee, inherits=Person, polymorphic_identity='employee')\n"
            "reg.map_imperatively(Pet, pet)\n",
        )

        assert set(entities) == {"Person", "Pet"}
        assert entities["Person"].relationships == [("Pet", "many", "pets")]


def test_column_without_a_type_has_no_dangling_colon() -> None:
    """A column whose type is unknown renders without ``name :``."""
    entity = EntityInfo(name="t", table_name="t", source="sqlalchemy")
    entity.fields = [FieldInfo(name="ref", type_str="")]

    output = PlantUMLGenerator({"t": entity}, {}).generate()

    assert "ref" in output
    assert "ref :" not in output
