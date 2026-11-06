"""Column settings inside ``Annotated[...]`` metadata, also through type aliases (#241)."""

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
            ("Mapped[intpk | None]", ("int", True, False, False, None)),
            ('Mapped["not ( an expression"]', ("not ( an expression", False, False, False, None)),
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
        """A model class shadows a same-named alias: a reference to it stays an edge."""
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
    profile: Mapped["Profile"] = relationship()
""",
        )
        assert ("Profile", "one", "profile") in entities["Account"].relationships
        assert [f.name for f in entities["Account"].fields] == ["id"]

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


class TestAliasScope:
    def test_conflicting_definitions_are_not_used(self, tmp_path: Path):
        (tmp_path / "a.py").write_text(
            "from typing import Annotated\nfrom sqlalchemy.orm import mapped_column\n\n"
            "pk = Annotated[int, mapped_column(primary_key=True)]\n",
            encoding="utf-8",
        )
        (tmp_path / "b.py").write_text(
            "from typing import Annotated\nfrom uuid import UUID\n"
            "from sqlalchemy.orm import mapped_column\n\n"
            "pk = Annotated[UUID, mapped_column(primary_key=True)]\n",
            encoding="utf-8",
        )
        (tmp_path / "models.py").write_text(
            HEADER + "\nclass Account(Base):\n    __tablename__ = 'account'\n    id: Mapped[pk]\n",
            encoding="utf-8",
        )
        entities, _ = parse_models_directory(tmp_path, include_patterns=["*.py"])
        assert _flags(_field(entities, "id")) == ("pk", False, False, False, None)

    def test_rebound_name_is_not_used(self, tmp_path: Path):
        entities = _parse(
            tmp_path,
            """
intpk = Annotated[int, mapped_column(primary_key=True)]
intpk = int


class Account(Base):
    __tablename__ = "account"
    id: Mapped[int] = mapped_column(primary_key=True)
    col: Mapped[intpk]
""",
        )
        assert _flags(_field(entities, "col")) == ("intpk", False, False, False, None)


class TestAliasesLeaveOtherNamesAlone:
    ALIASES = """
user = Annotated[int, mapped_column(ForeignKey("user.id"))]
str50 = Annotated[str, mapped_column(String(50))]
PositiveInt = Annotated[int, "gt0"]
"""

    @pytest.mark.parametrize(
        ("annotation", "type_str"),
        [
            # A Literal value is not a type, even if it spells an alias name.
            ('Mapped[Literal["str50", "other"]]', "Literal['str50', 'other']"),
            # A generic (subscripted) alias is not expanded.
            ("Mapped[str50[int]]", "str50[int]"),
            # An Annotated alias without mapped_column keeps its name.
            ("Mapped[PositiveInt]", "PositiveInt"),
        ],
    )
    def test_not_expanded(self, tmp_path: Path, annotation: str, type_str: str):
        entities = _parse(
            tmp_path,
            "from typing import Literal\n"
            + self.ALIASES
            + f"""

class Account(Base):
    __tablename__ = "account"
    id: Mapped[int] = mapped_column(primary_key=True)
    col: {annotation}
""",
        )
        assert _field(entities, "col").type_str == type_str

    def test_foreign_key_string_is_not_an_alias(self, tmp_path: Path):
        """`ForeignKey("user.id")` stays a string although an alias is named `user`."""
        entities = _parse(
            tmp_path,
            self.ALIASES
            + """

class Account(Base):
    __tablename__ = "account"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[Annotated[int, mapped_column(ForeignKey("user.id"))]]
    by_alias: Mapped[user]
""",
        )
        assert _field(entities, "owner_id").foreign_table == "user.id"
        assert _field(entities, "by_alias").foreign_table == "user.id"


class TestMergeLikeSqlAlchemy:
    def test_only_the_first_metadata_mapped_column_counts(self, tmp_path: Path):
        entities = _parse(
            tmp_path,
            """
class Account(Base):
    __tablename__ = "account"
    id: Mapped[int] = mapped_column(primary_key=True)
    col: Mapped[Annotated[int, mapped_column(index=True), mapped_column(unique=True)]]
""",
        )
        f = _field(entities, "col")
        assert (f.index, f.is_unique) == (True, False)

    def test_primary_key_from_metadata_sticks(self, tmp_path: Path):
        entities = _parse(
            tmp_path,
            """
intpk = Annotated[int, mapped_column(primary_key=True)]


class Account(Base):
    __tablename__ = "account"
    id: Mapped[intpk] = mapped_column(primary_key=False)
""",
        )
        assert _field(entities, "id").is_primary_key

    def test_default_from_metadata(self, tmp_path: Path):
        entities = _parse(
            tmp_path,
            """
class Account(Base):
    __tablename__ = "account"
    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[Annotated[str, mapped_column(default="new")]]
    other: Mapped[Annotated[str, mapped_column(default="new")]] = mapped_column(default="x")
""",
        )
        assert _field(entities, "status").default_value == "'new'"
        assert _field(entities, "other").default_value == "'x'"

    def test_sqlmodel_field_in_metadata_is_ignored(self, tmp_path: Path):
        """SQLModel does not apply Field() keys from Annotated metadata."""
        (tmp_path / "models.py").write_text(
            "from typing import Annotated\n"
            "from sqlmodel import Field, SQLModel\n\n\n"
            "class Account(SQLModel, table=True):\n"
            "    id: int = Field(primary_key=True)\n"
            "    code: Annotated[str, Field(primary_key=True, unique=True)]\n",
            encoding="utf-8",
        )
        entities, _ = parse_models_directory(tmp_path)
        code = _field(entities, "code")
        assert (code.is_primary_key, code.is_unique) == (False, False)
