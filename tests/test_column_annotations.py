"""Column types and nullability are read from the annotation's syntax tree (#236).

Covers column nullability and displayed type for every spelling of an optional
type, and SQLAlchemy class detection through qualified / collection-only
``Mapped`` wrappers.
"""

from pathlib import Path

import pytest

from erdify.config import FieldInfo
from erdify.parser import parse_models_directory


def _parse(tmp_path: Path, source: str) -> dict:
    (tmp_path / "models.py").write_text(source, encoding="utf-8")
    entities, _ = parse_models_directory(tmp_path)
    return entities


SQLALCHEMY = """
import typing
from typing import Annotated, Optional, Union

from sqlalchemy import orm
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class OptionalSettings:
    pass


class NoneableJSON:
    pass


class Account(Base):
    __tablename__ = "account"
    id: Mapped[int] = mapped_column(primary_key=True)
    col: {annotation} = mapped_column()
"""

PYDANTIC = """
import typing
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field


class OptionalSettings(dict):
    pass


class Account(BaseModel):
    col: {annotation}
"""


def _column(entities: dict, name: str = "col") -> FieldInfo:
    return next(f for f in entities["Account"].fields if f.name == name)


class TestColumnNullability:
    @pytest.mark.parametrize(
        ("annotation", "type_str", "nullable"),
        [
            # A class whose *name* contains "Optional" / "None" is not optional.
            ("Mapped[OptionalSettings]", "OptionalSettings", False),
            ("Mapped[NoneableJSON]", "NoneableJSON", False),
            # Every spelling of an optional type.
            ("Mapped[int | None]", "int", True),
            ("Mapped[None | int]", "int", True),
            ("Mapped[Optional[int]]", "int", True),
            ("Mapped[typing.Optional[int]]", "int", True),
            ("Mapped[Union[int, None]]", "int", True),
            ("Mapped[Optional[OptionalSettings]]", "OptionalSettings", True),
            # Qualified Mapped is unwrapped like the bare one.
            ("orm.Mapped[int]", "int", False),
            ("orm.Mapped[int | None]", "int", True),
            # Generic args keep their brackets.
            ("Mapped[list[str] | None]", "list[str]", True),
            ("Mapped[dict[str, int]]", "dict[str, int]", False),
        ],
    )
    def test_sqlalchemy(self, tmp_path: Path, annotation: str, type_str: str, nullable: bool):
        col = _column(_parse(tmp_path, SQLALCHEMY.format(annotation=annotation)))
        assert (col.type_str, col.is_nullable) == (type_str, nullable)

    @pytest.mark.parametrize(
        ("annotation", "type_str", "nullable"),
        [
            ("OptionalSettings", "OptionalSettings", False),
            ('Literal["None", "x"]', "Literal['None', 'x']", False),
            # Annotated is unwrapped, with and without an optional inside.
            ("Annotated[int, Field(gt=0)]", "int", False),
            ("Annotated[int | None, Field(gt=0)]", "int", True),
            ("Annotated[Optional[int], Field(gt=0)]", "int", True),
            ("Optional[Annotated[int, Field(gt=0)]]", "int", True),
            # A union of several types keeps them, minus None.
            ("int | str | None", "int | str", True),
            ("Union[int, str, None]", "Union[int, str]", True),
            ("Union[int, str]", "Union[int, str]", False),
            # A quoted forward reference resolves like the bare type.
            ('"int | None"', "int", True),
        ],
    )
    def test_pydantic(self, tmp_path: Path, annotation: str, type_str: str, nullable: bool):
        col = _column(_parse(tmp_path, PYDANTIC.format(annotation=annotation)))
        assert (col.type_str, col.is_nullable) == (type_str, nullable)

    def test_explicit_nullable_still_wins(self, tmp_path: Path):
        source = SQLALCHEMY.format(annotation="Mapped[int | None]").replace(
            "col: Mapped[int | None] = mapped_column()",
            "col: Mapped[int | None] = mapped_column(nullable=False)",
        )
        assert _column(_parse(tmp_path, source)).is_nullable is False


class TestSqlAlchemyDetection:
    @pytest.mark.parametrize(
        "annotation",
        [
            "orm.Mapped[int]",
            "sqlalchemy.orm.Mapped[int]",
        ],
    )
    def test_qualified_mapped_only(self, tmp_path: Path, annotation: str):
        source = f"""
import sqlalchemy
from sqlalchemy import orm


class Base(orm.DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "account"
    id: {annotation} = orm.mapped_column(primary_key=True)
"""
        entities = _parse(tmp_path, source)
        assert entities["Account"].source == "sqlalchemy"
        assert entities["Account"].fields[0].is_primary_key

    @pytest.mark.parametrize("wrapper", ["WriteOnlyMapped", "DynamicMapped"])
    def test_collection_only_mapped(self, tmp_path: Path, wrapper: str):
        """A class whose only annotated member is a collection relationship."""
        source = f"""
from sqlalchemy import Column, Integer
from sqlalchemy.orm import DeclarativeBase, {wrapper}, relationship


class Base(DeclarativeBase):
    pass


class Item(Base):
    __tablename__ = "item"
    id = Column(Integer, primary_key=True)


class Account(Base):
    __tablename__ = "account"
    id = Column(Integer, primary_key=True)
    items: {wrapper}["Item"] = relationship()
"""
        entities = _parse(tmp_path, source)
        assert entities["Account"].source == "sqlalchemy"
        assert ("Item", "many", "items") in entities["Account"].relationships
