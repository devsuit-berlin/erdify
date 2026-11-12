"""SQLAlchemy ``@declared_attr`` members (#298) and optional reverse to-one references (#299)."""

from pathlib import Path

from erdify.config import EntityInfo
from erdify.parser import parse_models_directory


def _parse(tmp_path: Path, src: str) -> dict[str, EntityInfo]:
    (tmp_path / "models.py").write_text(src, encoding="utf-8")
    entities, _ = parse_models_directory(tmp_path)
    return entities


class TestDeclaredAttr:
    def test_relationship_and_column_from_a_mixin(self, tmp_path: Path):
        entities = _parse(
            tmp_path,
            """
from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class OwnedMixin:
    @declared_attr
    def owner_id(cls) -> Mapped[int | None]:
        \"\"\"The owner's key.\"\"\"
        return mapped_column("owner_ref", ForeignKey("owner.id"))

    @declared_attr.cascading
    def owner(cls) -> Mapped["Owner | None"]:
        return relationship()


class Owner(Base):
    __tablename__ = "owner"
    id: Mapped[int] = mapped_column(primary_key=True)


class Document(OwnedMixin, Base):
    __tablename__ = "document"
    id: Mapped[int] = mapped_column(primary_key=True)
""",
        )
        doc = entities["Document"]
        assert [(f.name, f.foreign_table, f.is_nullable) for f in doc.fields] == [
            ("owner_ref", "owner.id", True),
            ("id", None, False),
        ]
        assert doc.relationships == [("Owner", "one", "owner")]
        assert doc.nullable_relationships == ["owner"]

    def test_qualified_decorator(self, tmp_path: Path):
        entities = _parse(
            tmp_path,
            """
from sqlalchemy import ForeignKey, orm
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Owner(Base):
    __tablename__ = "owner"
    id: Mapped[int] = mapped_column(primary_key=True)


class OwnedMixin:
    owner_id: Mapped[int] = mapped_column(ForeignKey("owner.id"))

    @orm.declared_attr
    def owner(cls) -> Mapped["Owner"]:
        return orm.relationship()


class Document(OwnedMixin, Base):
    __tablename__ = "document"
    id: Mapped[int] = mapped_column(primary_key=True)
""",
        )
        assert entities["Document"].relationships == [("Owner", "one", "owner")]

    def test_unreadable_methods_are_ignored(self, tmp_path: Path):
        """No return annotation, several statements, a directive, a plain method."""
        entities = _parse(
            tmp_path,
            """
from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Owner(Base):
    __tablename__ = "owner"
    id: Mapped[int] = mapped_column(primary_key=True)


class OwnedMixin:
    owner_id: Mapped[int] = mapped_column(ForeignKey("owner.id"))

    @declared_attr
    def owner(cls):
        return relationship("Owner")

    @declared_attr
    def note(cls) -> Mapped[str]:
        column = mapped_column()
        return column

    @declared_attr.directive
    def __table_args__(cls) -> tuple[object, ...]:
        return ()

    def label(cls) -> Mapped[str]:
        return mapped_column()


class Document(OwnedMixin, Base):
    __tablename__ = "document"
    id: Mapped[int] = mapped_column(primary_key=True)
""",
        )
        doc = entities["Document"]
        assert [f.name for f in doc.fields] == ["owner_id", "id"]
        assert doc.relationships == []

    def test_mixin_listed_first_keeps_its_column(self, tmp_path: Path):
        """A declared_attr counts as a value: a mixin listed first keeps its column."""
        entities = _parse(
            tmp_path,
            """
from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column


class Base(DeclarativeBase):
    pass


class NoteMixin:
    @declared_attr
    def note(cls) -> Mapped[str | None]:
        return mapped_column()


class Employee(Base):
    __tablename__ = "employee"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str]
    note: Mapped[str]
    __mapper_args__ = {"polymorphic_on": "kind"}


class Engineer(NoteMixin, Employee):
    __tablename__ = "engineer"
    __mapper_args__ = {"polymorphic_identity": "engineer"}
    id: Mapped[int] = mapped_column(ForeignKey("employee.id"), primary_key=True)

""",
        )
        assert [f.name for f in entities["Engineer"].fields] == ["note", "id"]


class TestReverseToOne:
    def test_referenced_side_is_optional(self, tmp_path: Path):
        entities = _parse(
            tmp_path,
            """
from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Device(Base):
    __tablename__ = "device"
    id: Mapped[int] = mapped_column(primary_key=True)
    license: Mapped["License"] = relationship(back_populates="device")


class License(Base):
    __tablename__ = "license"
    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("device.id"), unique=True)
    device: Mapped["Device"] = relationship(back_populates="license")
""",
        )
        assert entities["Device"].nullable_relationships == ["license"]
        assert entities["License"].nullable_relationships == []

    def test_foreign_key_in_a_mapped_parent_keeps_it_required(self, tmp_path: Path):
        """A joined-table subclass joins through its parent's foreign key: many-to-one."""
        entities = _parse(
            tmp_path,
            """
from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Company(Base):
    __tablename__ = "company"
    id: Mapped[int] = mapped_column(primary_key=True)


class Employee(Base):
    __tablename__ = "employee"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str]
    company_id: Mapped[int] = mapped_column(ForeignKey("company.id"))
    __mapper_args__ = {"polymorphic_on": "kind"}


class Engineer(Employee):
    __tablename__ = "engineer"
    id: Mapped[int] = mapped_column(ForeignKey("employee.id"), primary_key=True)
    company: Mapped["Company"] = relationship()
    __mapper_args__ = {"polymorphic_identity": "engineer"}
""",
        )
        assert entities["Engineer"].relationships == [("Company", "one", "company")]
        assert entities["Engineer"].nullable_relationships == []

    def test_self_reference_keeps_its_annotation(self, tmp_path: Path):
        """Its direction depends on ``remote_side=``, so the annotation decides."""
        entities = _parse(
            tmp_path,
            """
from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Node(Base):
    __tablename__ = "node"
    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int] = mapped_column(ForeignKey("node.id"))
    parent: Mapped["Node"] = relationship(remote_side=[id])
""",
        )
        assert entities["Node"].nullable_relationships == []
