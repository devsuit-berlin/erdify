"""Model references are recognized in every spelling of the annotation (#229).

Covers Pydantic/dataclass model references and SQLModel/SQLAlchemy
``Relationship()`` / ``relationship()`` targets.
"""

from pathlib import Path

import pytest

from erdify.generator import generate_mermaid
from erdify.parser import parse_models_directory


def _parse(tmp_path: Path, source: str) -> dict:
    (tmp_path / "models.py").write_text(source)
    entities, _ = parse_models_directory(tmp_path)
    return entities


PYDANTIC = """
import typing
from typing import Annotated, List, Optional, Sequence, Set, Union

import schemas
from pydantic import BaseModel, Field


class User(BaseModel):
    id: int


class Post(BaseModel):
    id: int
    ref: {annotation}
"""


class TestKeylessReferences:
    @pytest.mark.parametrize(
        ("annotation", "rel_type", "nullable"),
        [
            # Already supported; must keep working.
            ("User", "one", False),
            ("User | None", "one", True),
            ("Optional[User]", "one", True),
            ("list[User]", "many", False),
            ('"User"', "one", False),
            # #229
            ("Union[User, None]", "one", True),
            ("Union[None, User]", "one", True),
            ("None | User", "one", True),
            ("typing.Optional[User]", "one", True),
            ("typing.Union[User, None]", "one", True),
            ('"None | User"', "one", True),
            ('Optional["User"]', "one", True),
            ('Annotated[User | None, Field(description="x")]', "one", True),
            ("Annotated[User, Field()]", "one", False),
            ("Annotated[Optional[User], 1]", "one", True),
            ("Optional[Annotated[User, 1]]", "one", True),
            ("Union[list[User], None]", "many", False),
            ("typing.List[User]", "many", False),
            ("Annotated[list[User], 1]", "many", False),
            # Self-review of #229
            ("list[list[User]]", "many", False),  # nested lists (drawn on main too)
            ("List[List[User]]", "many", False),
            ("list[Optional[list[User]]]", "many", False),
            ('Union["User", "None"]', "one", True),  # string "None"
            ('User | "None"', "one", True),
            ("schemas.User", "one", False),  # module-qualified class
            ('"schemas.User"', "one", False),
            ("Optional[schemas.User]", "one", True),
            ("set[User]", "many", False),
            ("Set[User]", "many", False),
            ("frozenset[User]", "many", False),
            ("Sequence[User]", "many", False),
            ("tuple[User, ...]", "many", False),
            ("dict[str, User]", "many", False),
            ("Annotated[User, None]", "one", False),  # metadata None is not optional
            ("typing.Annotated[User | None, 1]", "one", True),
            ('" User "', "one", False),  # whitespace around a forward reference
        ],
    )
    def test_recognized(self, tmp_path: Path, annotation: str, rel_type: str, nullable: bool):
        post = _parse(tmp_path, PYDANTIC.format(annotation=annotation))["Post"]
        assert post.relationships == [("User", rel_type, "ref")]
        assert post.nullable_relationships == (["ref"] if nullable else [])
        assert [f.name for f in post.fields] == ["id"]

    @pytest.mark.parametrize(
        "annotation",
        [
            "Union[User, int]",  # not a single model
            "User | int",
            "int | None",
            "tuple[User, int]",  # fixed-length tuple of mixed types
            "dict[User, int]",  # the model is the key, not the value
            "Optional[int]",
            "get_type()",  # neither a name nor a subscript
            "tuple[()]",  # empty subscript
            "Union[get_type(), None]",  # single member that names no class
            "None",
            '"a\\x00b"',  # NUL byte: ValueError on Python 3.11, SyntaxError later
            '"User |"',  # unparsable forward reference
            '"get()[User]"',  # subscript of a call
        ],
    )
    def test_not_a_reference(self, tmp_path: Path, annotation: str):
        post = _parse(tmp_path, PYDANTIC.format(annotation=annotation))["Post"]
        assert post.relationships == []
        assert [f.name for f in post.fields] == ["id", "ref"]

    def test_dataclass(self, tmp_path: Path):
        src = """
from dataclasses import dataclass
from typing import Union


@dataclass
class User:
    id: int


@dataclass
class Post:
    id: int
    ref: Union[User, None]
"""
        post = _parse(tmp_path, src)["Post"]
        assert post.relationships == [("User", "one", "ref")]
        assert post.nullable_relationships == ["ref"]

    def test_drawn_optional(self, tmp_path: Path):
        out = generate_mermaid(_parse(tmp_path, PYDANTIC.format(annotation="Union[User, None]")))
        assert 'Post }o--o| User : "ref"' in out


SQLALCHEMY = """
import typing
from typing import List, Optional, Union

from sqlalchemy.orm import (
    DeclarativeBase,
    DynamicMapped,
    Mapped,
    WriteOnlyMapped,
    mapped_column,
    relationship,
)


class Base(DeclarativeBase):
    pass


class Team(Base):
    __tablename__ = "team"
    id: Mapped[int] = mapped_column(primary_key=True)


class Member(Base):
    __tablename__ = "member"
    id: Mapped[int] = mapped_column(primary_key=True)
    team: {annotation} = relationship()
"""


class TestRelationshipTargets:
    @pytest.mark.parametrize(
        ("annotation", "rel_type", "nullable"),
        [
            ('Mapped["Team"]', "one", False),
            ('Mapped[Optional["Team"]]', "one", True),
            ('Mapped[Union["Team", None]]', "one", True),
            ('Mapped["Team | None"]', "one", True),
            ('Mapped[None | "Team"]', "one", True),
            ('Mapped[typing.Optional["Team"]]', "one", True),
            ('Mapped[List["Team"]]', "many", False),
            ('Mapped["models.Team"]', "one", False),
            ('WriteOnlyMapped[list["Team"]]', "many", False),
            ('DynamicMapped["Team"]', "one", False),
            ('Mapped[set["Team"]]', "many", False),
            ('Mapped[dict[str, "Team"]]', "many", False),
        ],
    )
    def test_target(self, tmp_path: Path, annotation: str, rel_type: str, nullable: bool):
        member = _parse(tmp_path, SQLALCHEMY.format(annotation=annotation))["Member"]
        assert member.relationships == [("Team", rel_type, "team")]
        assert member.nullable_relationships == (["team"] if nullable else [])

    @pytest.mark.parametrize("annotation", ['Mapped[Union["Team", int]]', 'Mapped["Team | Other"]'])
    def test_unresolvable_target_is_dropped(self, tmp_path: Path, annotation: str):
        """A ``relationship()`` naming no single class adds no relationship and no edge."""
        entities = _parse(tmp_path, SQLALCHEMY.format(annotation=annotation))
        assert entities["Member"].relationships == []
        edges = [line for line in generate_mermaid(entities).splitlines() if "--" in line]
        assert not any("Member" in line and "Team" in line for line in edges)


SQLMODEL = """
from typing import Optional, Union

from sqlmodel import Field, Relationship, SQLModel


class Team(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)


class Member(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    team: {annotation} = Relationship()
"""


class TestSQLModelRelationship:
    @pytest.mark.parametrize(
        ("annotation", "nullable"),
        [
            ('Optional["Team"]', True),
            ('Union["Team", None]', True),
            ('"Team | None"', True),
            ('"Team"', False),
        ],
    )
    def test_target(self, tmp_path: Path, annotation: str, nullable: bool):
        member = _parse(tmp_path, SQLMODEL.format(annotation=annotation))["Member"]
        assert member.relationships == [("Team", "one", "team")]
        assert member.nullable_relationships == (["team"] if nullable else [])
