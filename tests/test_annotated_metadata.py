"""Column settings inside ``Annotated[...]`` metadata, also through type aliases (#241)."""

import sys
from pathlib import Path

import pytest

from erdify.config import EntityInfo, FieldInfo
from erdify.parser import parse_models_directory

HEADER = """
from typing import Annotated, Optional, TypeAlias

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "user"
    id: Mapped[int] = mapped_column(primary_key=True)
"""


def _parse(tmp_path: Path, body: str) -> dict[str, EntityInfo]:
    (tmp_path / "models.py").write_text(HEADER + body, encoding="utf-8")
    entities, _ = parse_models_directory(tmp_path)
    return entities


def _field(entities: dict[str, EntityInfo], name: str) -> FieldInfo:
    return next(f for f in entities["Account"].fields if f.name == name)


def _flags(f: FieldInfo) -> tuple[str, bool, bool, bool, str | None]:
    return (f.type_str, f.is_primary_key, f.is_nullable, f.is_foreign_key, f.foreign_table)


class TestInlineAnnotated:
    def test_issue_repro(self, tmp_path: Path):
        entities = _parse(
            tmp_path,
            """
class Account(Base):
    __tablename__ = "account"
    id: Mapped[Annotated[int, mapped_column(primary_key=True)]]
    code: Mapped[Annotated[str | None, mapped_column(nullable=False)]]
""",
        )
        assert _flags(_field(entities, "id")) == ("int", True, False, False, None)
        assert _flags(_field(entities, "code")) == ("str", False, False, False, None)

    def test_foreign_key_and_unique_in_metadata(self, tmp_path: Path):
        entities = _parse(
            tmp_path,
            """
class Account(Base):
    __tablename__ = "account"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Annotated[int, mapped_column(ForeignKey("user.id"), unique=True)]]
""",
        )
        f = _field(entities, "user_id")
        assert _flags(f) == ("int", False, False, True, "user.id")
        assert f.is_unique

    def test_assigned_mapped_column_wins(self, tmp_path: Path):
        """As in SQLAlchemy, the assigned mapped_column() overrides the Annotated one."""
        entities = _parse(
            tmp_path,
            """
class Account(Base):
    __tablename__ = "account"
    id: Mapped[int] = mapped_column(primary_key=True)
    note: Mapped[Annotated[str, mapped_column(nullable=True, index=True)]] = mapped_column(
        nullable=False
    )
""",
        )
        f = _field(entities, "note")
        assert (f.is_nullable, f.index) == (False, True)

    def test_other_metadata_is_ignored(self, tmp_path: Path):
        entities = _parse(
            tmp_path,
            """
class Account(Base):
    __tablename__ = "account"
    id: Mapped[Annotated[int, "doc", mapped_column(primary_key=True), 42]]
""",
        )
        assert _field(entities, "id").is_primary_key


class TestTypeAliases:
    ALIASES = """
intpk = Annotated[int, mapped_column(primary_key=True)]
str30: TypeAlias = Annotated[str, mapped_column(String(30))]
user_fk = Annotated[int, mapped_column(ForeignKey("user.id"))]
required_str = Annotated[Optional[str], mapped_column(nullable=False)]
"""

    @pytest.mark.parametrize(
        ("annotation", "expected"),
        [
            ("Mapped[intpk]", ("int", True, False, False, None)),
            ('Mapped["intpk"]', ("int", True, False, False, None)),
            ("Mapped[str30]", ("str", False, False, False, None)),
            ("Mapped[Optional[str30]]", ("str", False, True, False, None)),
            ("Mapped[user_fk]", ("int", False, False, True, "user.id")),
            ("Mapped[required_str]", ("str", False, False, False, None)),
        ],
    )
    def test_alias(self, tmp_path: Path, annotation: str, expected: tuple):
        entities = _parse(
            tmp_path,
            self.ALIASES
            + f"""

class Account(Base):
    __tablename__ = "account"
    col: {annotation}
""",
        )
        assert _flags(_field(entities, "col")) == expected

    def test_alias_defined_in_another_scanned_file(self, tmp_path: Path):
        (tmp_path / "types.py").write_text(
            "from typing import Annotated\n"
            "from sqlalchemy.orm import mapped_column\n\n"
            "intpk = Annotated[int, mapped_column(primary_key=True)]\n",
            encoding="utf-8",
        )
        (tmp_path / "models.py").write_text(
            HEADER
            + """
class Account(Base):
    __tablename__ = "account"
    id: Mapped[intpk]
""",
            encoding="utf-8",
        )
        entities, _ = parse_models_directory(tmp_path, include_patterns=["*.py"])
        assert _field(entities, "id").is_primary_key

    def test_class_name_is_not_an_alias(self, tmp_path: Path):
        """A model class shadows a same-named alias: it stays a reference, not a column."""
        entities = _parse(
            tmp_path,
            """
Profile = Annotated[int, mapped_column(primary_key=True)]


class Profile(Base):
    __tablename__ = "profile"
    id: Mapped[int] = mapped_column(primary_key=True)


class Account(Base):
    __tablename__ = "account"
    id: Mapped[int] = mapped_column(primary_key=True)
    other: Mapped[Annotated[int, "x"]]
""",
        )
        assert _field(entities, "other").type_str == "int"

    def test_self_referencing_alias_does_not_loop(self, tmp_path: Path):
        entities = _parse(
            tmp_path,
            """
loop = Annotated["loop", mapped_column(index=True)]


class Account(Base):
    __tablename__ = "account"
    id: Mapped[int] = mapped_column(primary_key=True)
    col: Mapped[loop]
""",
        )
        assert _field(entities, "col").index


@pytest.mark.skipif(sys.version_info < (3, 12), reason="`type X = ...` needs Python 3.12")
def test_type_statement_alias(tmp_path: Path):
    entities = _parse(
        tmp_path,
        """
type intpk = Annotated[int, mapped_column(primary_key=True)]


class Account(Base):
    __tablename__ = "account"
    id: Mapped[intpk]
""",
    )
    assert _field(entities, "id").is_primary_key
