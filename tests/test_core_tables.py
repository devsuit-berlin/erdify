"""SQLAlchemy Core tables and classes mapped to them (#297, #305, #306)."""

from pathlib import Path

from erdify.config import EntityInfo, FieldInfo
from erdify.generator import PlantUMLGenerator
from erdify.parser import parse_models_directory

CATALOG = Path(__file__).parent / "fixtures" / "sqlalchemy_edge_cases"


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
            ")\n",
        )

        columns = _columns(entities["ticket"])
        assert columns["id"].type_str == "int"
        assert columns["status"].type_str == "Status"
        assert columns["status"].default_value == "Status.OPEN"
        assert columns["opened"].type_str == "datetime"
        assert columns["tags"].type_str == "ARRAY"
        assert columns["priority"].default_value == "3"

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

    def test_foreign_key_through_a_column_key_names_the_column(self) -> None:
        entities, _ = parse_models_directory(CATALOG / "core_table_options.py")

        assert _columns(entities["office"])["region"].foreign_table == "region.region_id"

    def test_a_table_call_without_columns_is_not_drawn(self, tmp_path: Path) -> None:
        entities = _parse(
            tmp_path,
            "from rich.table import Table\n\nsummary = Table('Totals')\n",
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
        assert entities["Shelf"].relationships == [("Book", "many", "books")]


class TestMapImperatively:
    """``registry.map_imperatively(Class, table)`` (#306)."""

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
