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
from typing import Annotated, List, Optional, Union

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
            "dict[str, User]",  # not a supported container
            "list[list[User]]",  # nested containers
            "None",
            '"User |"',  # unparsable forward reference
            '"get()[User]"',  # subscript of a call
        ],
    )
    def test_not_a_reference(self, tmp_path: Path, annotation: str):
        post = _parse(tmp_path, PYDANTIC.format(annotation=annotation))["Post"]
        assert post.relationships == []
        assert [f.name for f in post.fields] == ["id", "ref"]

    def test_drawn_optional(self, tmp_path: Path):
        out = generate_mermaid(_parse(tmp_path, PYDANTIC.format(annotation="Union[User, None]")))
        assert 'Post }o--o| User : "ref"' in out


SQLALCHEMY = """
import typing
from typing import List, Optional, Union

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


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
        ],
    )
    def test_target(self, tmp_path: Path, annotation: str, rel_type: str, nullable: bool):
        member = _parse(tmp_path, SQLALCHEMY.format(annotation=annotation))["Member"]
        assert member.relationships == [("Team", rel_type, "team")]
        assert member.nullable_relationships == (["team"] if nullable else [])

    def test_unresolvable_target_keeps_historical_fallback(self, tmp_path: Path):
        """A ``relationship()`` whose annotation names no single model draws no edge."""
        entities = _parse(tmp_path, SQLALCHEMY.format(annotation='Mapped[Union["Team", int]]'))
        assert [rel[1:] for rel in entities["Member"].relationships] == [("one", "team")]
        assert "Member }o--|| Team" not in generate_mermaid(entities)
