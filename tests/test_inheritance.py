"""Inherited members resolve like Python's MRO (#228).

Each test parses real model source, so it covers the base-class merge in the
parser and, where relevant, the edges the generator draws from it.
"""

import time
from pathlib import Path

from erdify.generator import generate_mermaid
from erdify.parser import parse_models_directory


def _parse(tmp_path: Path, source: str) -> dict:
    (tmp_path / "models.py").write_text(source)
    entities, _ = parse_models_directory(tmp_path)
    return entities


def _field(entities: dict, entity: str, name: str):
    return next(f for f in entities[entity].fields if f.name == name)


DJANGO_DIAMOND = """
from django.db import models


class Account(models.Model):
    pass


class Other(models.Model):
    pass


class Root(models.Model):
    owner = models.OneToOneField(Account, on_delete=models.CASCADE)

    class Meta:
        abstract = True


class Left(Root):
    class Meta:
        abstract = True


class Right(Root):
    owner = models.OneToOneField(Other, on_delete=models.CASCADE, primary_key=True)

    class Meta:
        abstract = True


class Settings(Left, Right):
    pass
"""


class TestDiamond:
    """A sibling base's redeclaration replaces what the shared root declared."""

    def test_django_stale_relationship_is_dropped(self, tmp_path: Path):
        entities = _parse(tmp_path, DJANGO_DIAMOND)
        settings = entities["Settings"]
        assert [f.name for f in settings.fields] == ["owner_id"]
        assert settings.relationships == []
        owner = _field(entities, "Settings", "owner_id")
        assert owner.is_primary_key
        assert owner.foreign_table is not None and owner.foreign_table.startswith("other.")

    def test_django_single_edge(self, tmp_path: Path):
        out = generate_mermaid(_parse(tmp_path, DJANGO_DIAMOND))
        assert 'Settings |o--|| Other : "owner_id"' in out
        assert "Settings ||--|| Account" not in out
        assert "Settings |o--|| Account" not in out

    def test_pydantic_redeclared_in_sibling(self, tmp_path: Path):
        src = """
from pydantic import BaseModel


class User(BaseModel):
    id: int


class Root(BaseModel):
    user: User


class Left(Root):
    pass


class Right(Root):
    user: int


class Post(Left, Right):
    id: int
"""
        post = _parse(tmp_path, src)["Post"]
        assert post.relationships == []
        assert [f.name for f in post.fields] == ["user", "id"]


class TestBasePrecedence:
    """The first base in the MRO wins, as in Python."""

    def test_django(self, tmp_path: Path):
        src = """
from django.db import models


class Left(models.Model):
    name = models.CharField(max_length=10)

    class Meta:
        abstract = True


class Right(models.Model):
    name = models.IntegerField()

    class Meta:
        abstract = True


class Child(Left, Right):
    pass
"""
        entities = _parse(tmp_path, src)
        assert _field(entities, "Child", "name").type_str == "str"

    def test_sqlmodel_mixins(self, tmp_path: Path):
        src = """
from sqlmodel import Field, SQLModel


class LeftMixin:
    code: str


class RightMixin:
    code: int


class Item(LeftMixin, RightMixin, SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
"""
        entities = _parse(tmp_path, src)
        assert _field(entities, "Item", "code").type_str == "str"

    def test_class_body_still_wins(self, tmp_path: Path):
        src = """
from sqlmodel import Field, SQLModel


class LeftMixin:
    code: str


class Item(LeftMixin, SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    code: bytes
"""
        entities = _parse(tmp_path, src)
        assert _field(entities, "Item", "code").type_str == "bytes"

    def test_explicit_column_name_follows_mro(self, tmp_path: Path):
        """A constraint matches the DB name of the base that wins (#221)."""
        src = """
from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class LeftMixin:
    code: Mapped[str] = mapped_column("left_code")


class RightMixin:
    code: Mapped[str] = mapped_column("right_code")


class Item(LeftMixin, RightMixin, Base):
    __tablename__ = "item"
    __table_args__ = (UniqueConstraint("left_code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
"""
        entities = _parse(tmp_path, src)
        assert _field(entities, "Item", "code").is_unique


class TestFieldOrder:
    """Resolving by MRO must not reorder fields."""

    def test_diamond_order_is_unchanged(self, tmp_path: Path):
        src = """
from sqlmodel import Field, SQLModel


class Root:
    id: int | None = Field(default=None, primary_key=True)
    root: str


class Left(Root):
    left: str


class Right(Root):
    right: str
    root: int


class Item(Left, Right, SQLModel, table=True):
    own: str
"""
        entities = _parse(tmp_path, src)
        assert [f.name for f in entities["Item"].fields] == ["id", "root", "left", "right", "own"]
        # Right precedes Root in the MRO, so its redeclaration wins.
        assert _field(entities, "Item", "root").type_str == "int"


class TestInconsistentHierarchy:
    """A hierarchy without a valid MRO still parses (Python itself rejects it)."""

    def test_falls_back_without_crashing(self, tmp_path: Path):
        src = """
from sqlmodel import Field, SQLModel


class A:
    a: str


class B:
    b: str


class X(A, B):
    pass


class Y(B, A):
    pass


class Item(X, Y, SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
"""
        entities = _parse(tmp_path, src)
        assert {f.name for f in entities["Item"].fields} == {"id", "a", "b"}

    def test_self_named_base(self, tmp_path: Path):
        """``class User(User)`` (extending a namesake) resolves to itself; no loop."""
        src = """
from sqlmodel import Field, SQLModel


class Item(SQLModel):
    name: str


class Item(Item, SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
"""
        entities = _parse(tmp_path, src)
        assert [f.name for f in entities["Item"].fields] == ["id"]


class TestOrderWhenKindChanges:
    def test_column_keeps_its_position(self, tmp_path: Path):
        """An attribute that is a column in one base and a reference in another."""
        src = """
from pydantic import BaseModel


class Addon(BaseModel):
    id: int


class A(BaseModel):
    x: int
    y: int


class B(BaseModel):
    x: Addon


class C(A, B):
    z: int
"""
        c = _parse(tmp_path, src)["C"]
        assert [f.name for f in c.fields] == ["x", "y", "z"]
        assert c.relationships == []


class TestDjangoFieldRemoval:
    def test_none_removes_inherited_field(self, tmp_path: Path):
        """``owner = None`` removes a field inherited from an abstract base."""
        src = """
from django.db import models


class Tag(models.Model):
    pass


class Base(models.Model):
    owner = models.ForeignKey(Tag, on_delete=models.CASCADE)
    note = models.CharField(max_length=10)

    class Meta:
        abstract = True


class Item(Base):
    owner = None
"""
        entities = _parse(tmp_path, src)
        assert [f.name for f in entities["Item"].fields] == ["id", "note"]
        out = generate_mermaid(entities)
        assert not any(
            line.strip().startswith("Item ") and "Tag :" in line for line in out.splitlines()
        )


class TestDeepDiamonds:
    def test_stacked_diamonds_parse_quickly(self, tmp_path: Path):
        """The MRO is memoized; stacked diamonds must not blow up exponentially.

        Unmemoized, 29 stacked diamonds would take on the order of 2**29 steps,
        so the generous bound only catches a regression, never a slow runner.
        """
        lines = [
            "from pydantic import BaseModel",
            "",
            "",
            "class L0(BaseModel):",
            "    f0: int",
            "",
        ]
        for i in range(1, 30):
            lines += [
                f"class A{i}(L{i - 1}):",
                f"    a{i}: int",
                f"class B{i}(L{i - 1}):",
                f"    b{i}: int",
                f"class L{i}(A{i}, B{i}):",
                f"    l{i}: int",
                "",
            ]
        start = time.perf_counter()
        entities = _parse(tmp_path, "\n".join(lines))
        assert time.perf_counter() - start < 30
        assert len(entities["L29"].fields) == 1 + 3 * 29


class TestDjangoSiblingOrder:
    """Sibling bases never displace each other's fields (order as before #228)."""

    def test_same_kind_in_both_siblings(self, tmp_path: Path):
        src = """
from django.db import models


class Left(models.Model):
    code = models.CharField(max_length=5)
    left_only = models.IntegerField()

    class Meta:
        abstract = True


class Right(models.Model):
    code = models.IntegerField()
    right_only = models.IntegerField()

    class Meta:
        abstract = True


class Child(Left, Right):
    pass
"""
        entities = _parse(tmp_path, src)
        assert [f.name for f in entities["Child"].fields] == [
            "id",
            "code",
            "left_only",
            "right_only",
        ]
        assert _field(entities, "Child", "code").type_str == "str"

    def test_mixed_kind_in_siblings(self, tmp_path: Path):
        """A losing sibling's M2M neither survives nor moves the winning FK column."""
        src = """
from django.db import models


class Tag(models.Model):
    pass


class Left(models.Model):
    owner = models.ForeignKey(Tag, on_delete=models.CASCADE)

    class Meta:
        abstract = True


class Right(models.Model):
    owner = models.ManyToManyField(Tag)

    class Meta:
        abstract = True


class Child(Left, Right):
    note = models.IntegerField()
"""
        child = _parse(tmp_path, src)["Child"]
        assert [f.name for f in child.fields] == ["id", "owner_id", "note"]
        assert child.relationships == []

    def test_body_redeclaration_still_moves(self, tmp_path: Path):
        """A Django body redeclaring an inherited field lists it at the body (as before)."""
        src = """
from django.db import models


class Base(models.Model):
    code = models.CharField(max_length=5)
    other = models.IntegerField()

    class Meta:
        abstract = True


class Child(Base):
    code = models.IntegerField()
"""
        child = _parse(tmp_path, src)["Child"]
        assert [f.name for f in child.fields] == ["id", "other", "code"]


class TestBodyKindChange:
    """A body redeclaring an inherited attribute as another kind replaces it."""

    def test_column_to_reference(self, tmp_path: Path):
        src = """
from pydantic import BaseModel


class User(BaseModel):
    id: int


class Base(BaseModel):
    user: int


class Post(Base):
    user: User
"""
        post = _parse(tmp_path, src)["Post"]
        assert post.fields == []
        assert post.relationships == [("User", "one", "user")]

    def test_reference_to_column(self, tmp_path: Path):
        src = """
from pydantic import BaseModel


class User(BaseModel):
    id: int


class Base(BaseModel):
    user: User


class Post(Base):
    user: int
"""
        post = _parse(tmp_path, src)["Post"]
        assert [f.name for f in post.fields] == ["user"]
        assert post.relationships == []


class TestDjangoInheritedSelfReference:
    """``"self"`` in an abstract base points at each concrete subclass, as in Django."""

    SRC = """
from django.db import models


class TreeBase(models.Model):
    parent = models.ForeignKey("self", null=True, on_delete=models.CASCADE)
    peers = models.ManyToManyField("self")

    class Meta:
        abstract = True


class Node(TreeBase):
    code = models.CharField(max_length=5, primary_key=True)


class Leaf(TreeBase):
    pass
"""

    def test_foreign_key(self, tmp_path: Path):
        entities = _parse(tmp_path, self.SRC)
        node = _field(entities, "Node", "parent_id")
        assert node.foreign_table == "node.code"
        assert node.type_str == "str"
        assert _field(entities, "Leaf", "parent_id").foreign_table == "leaf.id"
        out = generate_mermaid(entities)
        assert 'Node }o--o| Node : "parent_id"' in out
        assert 'Leaf }o--o| Leaf : "parent_id"' in out

    def test_many_to_many(self, tmp_path: Path):
        entities = _parse(tmp_path, self.SRC)
        assert entities["Node"].relationships == [("Node", "many_to_many", "peers")]
        assert entities["Leaf"].relationships == [("Leaf", "many_to_many", "peers")]
