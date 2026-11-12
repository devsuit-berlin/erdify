"""SQLAlchemy mapped-class inheritance: joined-table (#293) and single-table (#302).

A mapped parent keeps its columns in its own table: a joined-table subclass
(``__tablename__`` of its own) gets only its own columns and those of its own
mixins, and a single-table subclass (no table of its own) adds its columns to
the nearest ancestor that has a table.
"""

from pathlib import Path

from erdify.generator import generate_mermaid
from erdify.parser import parse_models_directory

HEADER = (
    "from datetime import datetime\n"
    "from sqlalchemy import Column, ForeignKey, Integer, String, Table\n"
    "from sqlalchemy.orm import (\n"
    "    DeclarativeBase, Mapped, declared_attr, mapped_column, registry, relationship,\n"
    ")\n\n\n"
    "class Base(DeclarativeBase):\n    pass\n\n\n"
)


def _parse(tmp_path: Path, body: str) -> dict:
    (tmp_path / "models.py").write_text(HEADER + body)
    entities, _ = parse_models_directory(tmp_path)
    return entities


def _columns(entities: dict, name: str) -> list[str]:
    return [f.name for f in entities[name].fields]


EMPLOYEE = """
class Stamp:
    created: Mapped[datetime | None]


class Audit:
    note: Mapped[str | None]


class Employee(Stamp, Base):
    __tablename__ = "employee"
    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str]
    __mapper_args__ = {"polymorphic_identity": "employee", "polymorphic_on": "type"}


class Engineer(Audit, Employee):
    __tablename__ = "engineer"
    id: Mapped[int] = mapped_column(ForeignKey("employee.id"), primary_key=True)
    language: Mapped[str]
    __mapper_args__ = {"polymorphic_identity": "engineer"}
"""


class TestJoinedTable:
    def test_subclass_has_only_its_own_columns(self, tmp_path: Path) -> None:
        entities = _parse(tmp_path, EMPLOYEE)
        assert sorted(_columns(entities, "Employee")) == ["created", "id", "type"]
        # The parent's mixin (Stamp) stays on the parent; the subclass's own one is copied.
        assert sorted(_columns(entities, "Engineer")) == ["id", "language", "note"]

    def test_subclass_key_references_the_parent(self, tmp_path: Path) -> None:
        entities = _parse(tmp_path, EMPLOYEE)
        key = next(f for f in entities["Engineer"].fields if f.name == "id")
        assert key.is_primary_key
        assert key.foreign_table == "employee.id"

    def test_parent_relationship_stays_on_the_parent(self, tmp_path: Path) -> None:
        entities = _parse(
            tmp_path,
            "class Owner(Base):\n    __tablename__ = 'owner'\n"
            "    id: Mapped[int] = mapped_column(primary_key=True)\n\n\n"
            "class Pet(Base):\n    __tablename__ = 'pet'\n"
            "    id: Mapped[int] = mapped_column(primary_key=True)\n"
            "    owner_id: Mapped[int] = mapped_column(ForeignKey('owner.id'))\n"
            "    owner: Mapped[Owner] = relationship()\n\n\n"
            "class Dog(Pet):\n    __tablename__ = 'dog'\n"
            "    id: Mapped[int] = mapped_column(ForeignKey('pet.id'), primary_key=True)\n",
        )
        assert _columns(entities, "Dog") == ["id"]
        assert entities["Dog"].relationships == []
        assert [r[2] for r in entities["Pet"].relationships] == ["owner"]

    def test_mixin_does_not_redeclare_a_parent_column(self, tmp_path: Path) -> None:
        """SQLAlchemy keeps the mapped parent's column over a mixin's annotation."""
        entities = _parse(
            tmp_path,
            "class Audit:\n    type: Mapped[str | None]\n    note: Mapped[str | None]\n\n\n"
            "class Employee(Base):\n    __tablename__ = 'employee'\n"
            "    id: Mapped[int] = mapped_column(primary_key=True)\n"
            "    type: Mapped[str]\n"
            "    __mapper_args__ = {'polymorphic_on': 'type', 'polymorphic_identity': 'e'}\n\n\n"
            "class Engineer(Audit, Employee):\n    __tablename__ = 'engineer'\n"
            "    id: Mapped[int] = mapped_column(ForeignKey('employee.id'), primary_key=True)\n"
            "    __mapper_args__ = {'polymorphic_identity': 'g'}\n\n\n"
            "class Intern(Audit, Employee):\n"
            "    __mapper_args__ = {'polymorphic_identity': 'i'}\n",
        )
        assert sorted(_columns(entities, "Engineer")) == ["id", "note"]
        kind = next(f for f in entities["Employee"].fields if f.name == "type")
        assert not kind.is_nullable

    def test_redeclared_under_another_attribute(self, tmp_path: Path) -> None:
        """``use_existing_column`` matches by column name, not attribute."""
        entities = _parse(
            tmp_path,
            "class Vehicle(Base):\n    __tablename__ = 'vehicle'\n"
            "    id: Mapped[int] = mapped_column(primary_key=True)\n"
            "    name: Mapped[str] = mapped_column('nm')\n\n\n"
            "class Car(Vehicle):\n"
            "    alias: Mapped[str | None] = mapped_column('nm', use_existing_column=True)\n",
        )
        assert _columns(entities, "Vehicle") == ["id", "nm"]
        assert entities["Vehicle"].fields[1].is_nullable

    def test_subclass_of_an_imperative_mapping_adds_nothing(self, tmp_path: Path) -> None:
        """An imperative mapping maps only its table's columns, never annotations."""
        entities = _parse(
            tmp_path,
            "mapper_registry = registry()\n"
            "user = Table('user', mapper_registry.metadata,"
            " Column('id', Integer, primary_key=True))\n\n\n"
            "class User:\n    id: int\n\n\n"
            "class Admin(User):\n    level: int\n\n\n"
            "mapper_registry.map_imperatively(User, user)\n",
        )
        assert _columns(entities, "User") == ["id"]


class TestNotReadable:
    """Subclasses whose table erdify can't see are left out, not merged into the parent."""

    def test_declared_attr_tablename_from_a_mixin(self, tmp_path: Path) -> None:
        entities = _parse(
            tmp_path,
            "class Named:\n    @declared_attr.directive\n"
            "    def __tablename__(cls) -> str:\n        return cls.__name__.lower()\n\n\n"
            "class Employee(Base):\n    __tablename__ = 'employee'\n"
            "    id: Mapped[int] = mapped_column(primary_key=True)\n\n\n"
            "class Engineer(Named, Employee):\n"
            "    id: Mapped[int] = mapped_column(ForeignKey('employee.id'), primary_key=True)\n"
            "    language: Mapped[str]\n",
        )
        assert set(entities) == {"Employee"}
        assert _columns(entities, "Employee") == ["id"]

    def test_own_declared_attr_tablename(self, tmp_path: Path) -> None:
        entities = _parse(
            tmp_path,
            "class Employee(Base):\n    __tablename__ = 'employee'\n"
            "    id: Mapped[int] = mapped_column(primary_key=True)\n\n\n"
            "class Engineer(Employee):\n    @declared_attr.directive\n"
            "    def __tablename__(cls) -> str:\n        return 'engineer'\n\n"
            "    id: Mapped[int] = mapped_column(ForeignKey('employee.id'), primary_key=True)\n"
            "    language: Mapped[str]\n",
        )
        assert _columns(entities, "Employee") == ["id"]

    def test_unresolved_table(self, tmp_path: Path) -> None:
        entities = _parse(
            tmp_path,
            "tables = {\n    'engineer': Table('engineer', Base.metadata,\n"
            "        Column('id', Integer, ForeignKey('employee.id'), primary_key=True)),\n}\n\n\n"
            "class Employee(Base):\n    __tablename__ = 'employee'\n"
            "    id: Mapped[int] = mapped_column(primary_key=True)\n\n\n"
            "class Engineer(Employee):\n    __table__ = tables['engineer']\n"
            "    language: Mapped[str | None]\n\n\n"
            "class Lead(Engineer):\n    level: Mapped[int | None]\n",
        )
        assert _columns(entities, "Employee") == ["id"]

    def test_subclass_of_an_undetected_table(self, tmp_path: Path) -> None:
        entities = _parse(
            tmp_path,
            "class Employee(Base):\n    __tablename__ = 'employee'\n"
            "    id: Mapped[int] = mapped_column(primary_key=True)\n\n\n"
            "class Manager(Employee):\n    __tablename__ = 'manager'\n"
            "    id = mapped_column(ForeignKey('employee.id'), primary_key=True)\n\n\n"
            "class Lead(Manager):\n    level: Mapped[int | None]\n",
        )
        assert set(entities) == {"Employee"}
        assert _columns(entities, "Employee") == ["id"]


class TestSingleTable:
    def test_subclass_columns_join_the_parent_table(self, tmp_path: Path) -> None:
        entities = _parse(
            tmp_path,
            "class Vehicle(Base):\n    __tablename__ = 'vehicle'\n"
            "    id: Mapped[int] = mapped_column(primary_key=True)\n"
            "    kind: Mapped[str]\n\n\n"
            "class Car(Vehicle):\n    wheels: Mapped[int | None]\n\n\n"
            "class Truck(Vehicle):\n    payload: Mapped[int]\n",
        )
        assert set(entities) == {"Vehicle"}
        assert _columns(entities, "Vehicle") == ["id", "kind", "wheels", "payload"]
        # SQLAlchemy keeps the declared nullability.
        payload = next(f for f in entities["Vehicle"].fields if f.name == "payload")
        assert not payload.is_nullable

    def test_nested_and_mixin_columns(self, tmp_path: Path) -> None:
        entities = _parse(
            tmp_path,
            EMPLOYEE + "\n\nclass Lead(Engineer):\n    level: Mapped[int]\n"
            "    __mapper_args__ = {'polymorphic_identity': 'lead'}\n\n\n"
            "class Intern(Audit, Employee):\n    school: Mapped[str]\n"
            "    __mapper_args__ = {'polymorphic_identity': 'intern'}\n\n\n"
            "class Junior(Intern):\n    mentor: Mapped[str | None]\n"
            "    __mapper_args__ = {'polymorphic_identity': 'junior'}\n",
        )
        assert set(entities) == {"Employee", "Engineer"}
        # Lead is stored in its nearest table, Engineer's; Junior in Employee's.
        assert sorted(_columns(entities, "Engineer")) == ["id", "language", "level", "note"]
        assert sorted(_columns(entities, "Employee")) == [
            "created",
            "id",
            "mentor",
            "note",
            "school",
            "type",
        ]

    def test_explicit_column_name_and_foreign_key(self, tmp_path: Path) -> None:
        entities = _parse(
            tmp_path,
            "class Depot(Base):\n    __tablename__ = 'depot'\n"
            "    id: Mapped[int] = mapped_column(primary_key=True)\n\n\n"
            "class Vehicle(Base):\n    __tablename__ = 'vehicle'\n"
            "    id: Mapped[int] = mapped_column(primary_key=True)\n\n\n"
            "class Bus(Vehicle):\n"
            "    seats: Mapped[int | None] = mapped_column('n_seats')\n"
            "    depot_id: Mapped[int | None] = mapped_column(ForeignKey('depot.id'))\n",
        )
        assert _columns(entities, "Vehicle") == ["id", "n_seats", "depot_id"]
        fk = next(f for f in entities["Vehicle"].fields if f.name == "depot_id")
        assert fk.foreign_table == "depot.id"

    def test_redeclared_column_keeps_its_first_declaration(self, tmp_path: Path) -> None:
        """``use_existing_column=True`` reuses the column; only nullability is the later one."""
        entities = _parse(
            tmp_path,
            "class Vehicle(Base):\n    __tablename__ = 'vehicle'\n"
            "    id: Mapped[int] = mapped_column(primary_key=True)\n"
            "    name: Mapped[str]\n\n\n"
            "class Car(Vehicle):\n"
            "    name: Mapped[str | None] = mapped_column(use_existing_column=True)\n"
            "    seats: Mapped[int | None]\n\n\n"
            "class Truck(Vehicle):\n"
            "    seats: Mapped[str] = mapped_column(use_existing_column=True, index=True)\n",
        )
        assert _columns(entities, "Vehicle") == ["id", "name", "seats"]
        fields = {f.name: f for f in entities["Vehicle"].fields}
        assert fields["name"].is_nullable  # Car's annotation
        seats = fields["seats"]
        assert (seats.type_str, seats.index, seats.is_nullable) == ("int", False, False)

    def test_tablename_none_is_single_table(self, tmp_path: Path) -> None:
        """Also when a mixin computes a table name: the class's own None comes first."""
        entities = _parse(
            tmp_path,
            "class Named:\n    @declared_attr.directive\n"
            "    def __tablename__(cls) -> str:\n        return cls.__name__.lower()\n\n\n"
            "class Employee(Base):\n    __tablename__ = 'employee'\n"
            "    id: Mapped[int] = mapped_column(primary_key=True)\n\n\n"
            "class Manager(Named, Employee):\n    __tablename__ = None\n"
            "    budget: Mapped[int | None]\n",
        )
        assert set(entities) == {"Employee"}
        assert _columns(entities, "Employee") == ["id", "budget"]

    def test_parent_mapped_to_a_core_table(self, tmp_path: Path) -> None:
        entities = _parse(
            tmp_path,
            "vehicle = Table('vehicle', Base.metadata,\n"
            "    Column('id', Integer, primary_key=True), Column('kind', String))\n\n\n"
            "class Vehicle(Base):\n    __table__ = vehicle\n\n\n"
            "class Car(Vehicle):\n"
            "    wheels: Mapped[int | None] = mapped_column('n_wheels')\n"
            "    kind: Mapped[str] = mapped_column(use_existing_column=True)\n",
        )
        assert set(entities) == {"Vehicle"}
        assert _columns(entities, "Vehicle") == ["id", "kind", "n_wheels"]
        kind = next(f for f in entities["Vehicle"].fields if f.name == "kind")
        assert not kind.is_nullable

    def test_subclass_relationships_are_not_drawn_yet(self, tmp_path: Path) -> None:
        """#317: the foreign key is drawn on the parent's table, the relationships are not."""
        entities = _parse(
            tmp_path,
            "class Depot(Base):\n    __tablename__ = 'depot'\n"
            "    id: Mapped[int] = mapped_column(primary_key=True)\n"
            "    cars: Mapped[list['Car']] = relationship(back_populates='depot')\n\n\n"
            "class Vehicle(Base):\n    __tablename__ = 'vehicle'\n"
            "    id: Mapped[int] = mapped_column(primary_key=True)\n\n\n"
            "class Car(Vehicle):\n"
            "    depot_id: Mapped[int | None] = mapped_column(ForeignKey('depot.id'))\n"
            "    depot: Mapped[Depot | None] = relationship(back_populates='cars')\n",
        )
        fk = next(f for f in entities["Vehicle"].fields if f.name == "depot_id")
        assert fk.foreign_table == "depot.id"
        assert entities["Vehicle"].relationships == []
        # Kept in the IR, but Car has no entity, so no edge is drawn for it.
        assert entities["Depot"].relationships == [("Car", "many", "cars")]
        edges = [line for line in generate_mermaid(entities, {}).splitlines() if "--" in line]
        assert edges == ['    Vehicle }o--o| Depot : "depot_id"']

    def test_abstract_subclass_adds_nothing(self, tmp_path: Path) -> None:
        entities = _parse(
            tmp_path,
            "class Mixin:\n    extra: Mapped[str | None]\n\n\n"
            "class Vehicle(Base):\n    __tablename__ = 'vehicle'\n"
            "    id: Mapped[int] = mapped_column(primary_key=True)\n\n\n"
            "class Draft(Mixin, Vehicle):\n    __abstract__ = True\n"
            "    draft: Mapped[str | None]\n\n\n"
            "class Unused(Vehicle):\n    __abstract__: bool = True\n"
            "    unused: Mapped[str | None]\n",
        )
        assert set(entities) == {"Vehicle"}
        assert _columns(entities, "Vehicle") == ["id"]
