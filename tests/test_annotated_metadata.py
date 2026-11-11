"""Column settings inside ``Annotated[...]`` metadata, also through type aliases (#241)."""

import sys
from pathlib import Path

import pytest

from erdify.config import EntityInfo, FieldInfo
from erdify.parser import parse_models_directory

HEADER = """
from typing import Annotated, Optional, TypeAlias

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


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
    profile_id: Mapped[int] = mapped_column(ForeignKey("profile.id"))
    profile: Mapped["Profile"] = relationship()
""",
        )
        assert ("Profile", "one", "profile") in entities["Account"].relationships
        assert [f.name for f in entities["Account"].fields] == ["id", "profile_id"]

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


class TestCopilotRound1:
    def test_import_under_alias_name_shadows_it(self, tmp_path: Path):
        entities = _parse(
            tmp_path,
            """
intpk = Annotated[int, mapped_column(primary_key=True)]
from uuid import UUID as intpk


class Account(Base):
    __tablename__ = "account"
    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[intpk]
""",
        )
        assert _flags(_field(entities, "token")) == ("intpk", False, False, False, None)

    def test_import_of_the_alias_itself_keeps_it(self, tmp_path: Path):
        """Defined in types.py, imported in models.py: the alias applies."""
        (tmp_path / "types.py").write_text(
            "from typing import Annotated\n"
            "from sqlalchemy.orm import mapped_column\n\n"
            "intpk = Annotated[int, mapped_column(primary_key=True)]\n",
            encoding="utf-8",
        )
        (tmp_path / "models.py").write_text(
            "from .types import intpk\n"
            + HEADER
            + "\nclass Account(Base):\n    __tablename__ = 'account'\n    id: Mapped[intpk]\n",
            encoding="utf-8",
        )
        entities, _ = parse_models_directory(tmp_path, include_patterns=["*.py"])
        assert _field(entities, "id").is_primary_key

    @pytest.mark.parametrize("rebinding", ["intpk = other = str", "intpk, other = str, int"])
    def test_chained_or_unpacking_rebinding(self, tmp_path: Path, rebinding: str):
        entities = _parse(
            tmp_path,
            f"""
intpk = Annotated[int, mapped_column(primary_key=True)]
{rebinding}


class Account(Base):
    __tablename__ = "account"
    id: Mapped[int] = mapped_column(primary_key=True)
    col: Mapped[intpk]
""",
        )
        assert _field(entities, "col").type_str == "intpk"

    def test_other_frameworks_ignore_mapped_column_metadata(self, tmp_path: Path):
        (tmp_path / "models.py").write_text(
            "from dataclasses import dataclass\n"
            "from typing import Annotated\n"
            "from sqlalchemy.orm import mapped_column\n\n"
            "intpk = Annotated[int, mapped_column(primary_key=True)]\n\n\n"
            "@dataclass\n"
            "class Dto:\n"
            "    id: intpk\n"
            '    status: Annotated[str, mapped_column(default="new")]\n',
            encoding="utf-8",
        )
        entities, _ = parse_models_directory(tmp_path)
        fields = {f.name: f for f in entities["Dto"].fields}
        assert (fields["id"].type_str, fields["id"].is_primary_key) == ("intpk", False)
        assert fields["status"].default_value is None

    def test_unrenderable_assigned_default_is_not_replaced(self, tmp_path: Path):
        entities = _parse(
            tmp_path,
            """
def make_status() -> str:
    return "new"


class Account(Base):
    __tablename__ = "account"
    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[Annotated[str, mapped_column(default="new")]] = mapped_column(
        default=make_status
    )
""",
        )
        assert _field(entities, "status").default_value is None


def test_assigned_plain_value_maps_no_column(tmp_path: Path):
    """`x: Mapped[T] = "x"` is a plain class attribute in SQLAlchemy, not a column (#294)."""
    entities = _parse(
        tmp_path,
        """
class Account(Base):
    __tablename__ = "account"
    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[Annotated[str, mapped_column(default="new")]] = "x"
    note: Mapped[str | None] = None
""",
    )
    assert [f.name for f in entities["Account"].fields] == ["id", "note"]


def test_assigned_call_is_still_a_column(tmp_path: Path):
    """Any call may return mapped_column() (a project helper), so it stays a column."""
    entities = _parse(
        tmp_path,
        """
def make_column():
    return mapped_column()


class Account(Base):
    __tablename__ = "account"
    id: Mapped[int] = mapped_column(primary_key=True)
    created: Mapped[str] = make_column()
""",
    )
    assert [f.name for f in entities["Account"].fields] == ["id", "created"]


def test_assigned_name_is_still_a_column(tmp_path: Path):
    """A module-level `fk = mapped_column(...)` assigned by name is a column."""
    entities = _parse(
        tmp_path,
        """
owner_fk = mapped_column()


class Account(Base):
    __tablename__ = "account"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = owner_fk
""",
    )
    assert [f.name for f in entities["Account"].fields] == ["id", "owner_id"]


def test_assigned_none_keeps_metadata_default(tmp_path: Path):
    """`= None` is unset in SQLAlchemy: the default in the metadata applies."""
    entities = _parse(
        tmp_path,
        """
class Account(Base):
    __tablename__ = "account"
    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[Annotated[str | None, mapped_column(default="new")]] = None
""",
    )
    assert _field(entities, "status").default_value == "'new'"


class TestCopilotRound2:
    def test_reading_an_alias_in_an_assignment_target_keeps_it(self, tmp_path: Path):
        entities = _parse(
            tmp_path,
            """
intpk = Annotated[int, mapped_column(primary_key=True)]
TYPE_MAP: dict[object, object] = {}
TYPE_MAP[intpk] = Integer


class Account(Base):
    __tablename__ = "account"
    id: Mapped[intpk]
""",
        )
        assert _flags(_field(entities, "id")) == ("int", True, False, False, None)

    def test_nested_annotated_alias(self, tmp_path: Path):
        entities = _parse(
            tmp_path,
            """
intpk = Annotated[Annotated[int, mapped_column(primary_key=True)], "tag"]


class Account(Base):
    __tablename__ = "account"
    id: Mapped[intpk]
""",
        )
        assert _flags(_field(entities, "id")) == ("int", True, False, False, None)

    def test_insert_default_counts_as_assigned_default(self, tmp_path: Path):
        entities = _parse(
            tmp_path,
            """
def make_status() -> str:
    return "new"


class Account(Base):
    __tablename__ = "account"
    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[Annotated[str, mapped_column(default="meta")]] = mapped_column(
        insert_default=make_status
    )
""",
        )
        assert _field(entities, "status").default_value is None

    def test_none_flags_are_unspecified(self, tmp_path: Path):
        entities = _parse(
            tmp_path,
            """
class Account(Base):
    __tablename__ = "account"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[Annotated[str, mapped_column(index=True, unique=True)]] = mapped_column(
        index=None, unique=None
    )
    other: Mapped[Annotated[str, mapped_column(index=True)]] = mapped_column(index=False)
""",
        )
        code = _field(entities, "code")
        assert (code.index, code.is_unique) == (True, True)
        assert _field(entities, "other").index is False


def test_same_module_import_replaces_the_alias(tmp_path: Path):
    """`UUID = Annotated[...]` then `from uuid import UUID`: the name is the import."""
    entities = _parse(
        tmp_path,
        """
UUID = Annotated[int, mapped_column(index=True)]
from uuid import UUID


class Account(Base):
    __tablename__ = "account"
    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[UUID]
""",
    )
    token = _field(entities, "token")
    assert (token.type_str, token.index) == ("UUID", False)


class TestModuleScope:
    """Aliases resolve like Python names: per module, through imports (#249, #250)."""

    TYPES = (
        "from typing import Annotated\n"
        "from sqlalchemy.orm import mapped_column\n\n"
        "UUID = Annotated[int, mapped_column(index=True)]\n"
        "intpk = Annotated[int, mapped_column(primary_key=True)]\n"
        "taggedpk = Annotated[intpk, 'tag']\n"
    )

    def _two_files(self, tmp_path: Path, models_head: str, body: str) -> dict[str, EntityInfo]:
        (tmp_path / "types.py").write_text(self.TYPES, encoding="utf-8")
        (tmp_path / "models.py").write_text(
            models_head + HEADER + "\nclass Account(Base):\n    __tablename__ = 'account'\n" + body,
            encoding="utf-8",
        )
        entities, _ = parse_models_directory(tmp_path, include_patterns=["*.py"])
        return entities

    def test_unrelated_import_in_another_module_is_not_the_alias(self, tmp_path: Path):
        """#250: types.py's alias `UUID` does not apply where `UUID` is imported from uuid."""
        entities = self._two_files(
            tmp_path,
            "from uuid import UUID\n",
            "    id: Mapped[int] = mapped_column(primary_key=True)\n    token: Mapped[UUID]\n",
        )
        token = _field(entities, "token")
        assert (token.type_str, token.index) == ("UUID", False)

    @pytest.mark.parametrize(
        "head",
        ["from .types import intpk\n", "from .types import *\n"],
    )
    def test_import_from_the_defining_module(self, tmp_path: Path, head: str):
        entities = self._two_files(tmp_path, head, "    id: Mapped[intpk]\n")
        assert _flags(_field(entities, "id")) == ("int", True, False, False, None)

    def test_renamed_import(self, tmp_path: Path):
        entities = self._two_files(
            tmp_path, "from .types import intpk as Key\n", "    id: Mapped[Key]\n"
        )
        assert _flags(_field(entities, "id")) == ("int", True, False, False, None)

    def test_derived_alias(self, tmp_path: Path):
        """#249: `taggedpk = Annotated[intpk, "tag"]` carries intpk's primary key."""
        entities = self._two_files(
            tmp_path, "from .types import taggedpk\n", "    id: Mapped[taggedpk]\n"
        )
        assert _flags(_field(entities, "id")) == ("int", True, False, False, None)

    def test_derived_alias_in_the_same_module(self, tmp_path: Path):
        entities = _parse(
            tmp_path,
            """
intpk = Annotated[int, mapped_column(primary_key=True)]
taggedpk = Annotated[intpk, "tag"]


class Account(Base):
    __tablename__ = "account"
    id: Mapped[taggedpk]
""",
        )
        assert _flags(_field(entities, "id")) == ("int", True, False, False, None)

    def test_last_binding_wins(self, tmp_path: Path):
        """A rebinding later in the module counts, an earlier one does not."""
        entities = _parse(
            tmp_path,
            """
intpk = int
intpk = Annotated[int, mapped_column(primary_key=True)]


class Account(Base):
    __tablename__ = "account"
    id: Mapped[intpk]
""",
        )
        assert _field(entities, "id").is_primary_key

    def test_mutually_recursive_aliases_do_not_loop(self, tmp_path: Path):
        entities = _parse(
            tmp_path,
            """
a = Annotated[b, mapped_column(index=True)]
b = Annotated[a, mapped_column(index=True)]


class Account(Base):
    __tablename__ = "account"
    id: Mapped[int] = mapped_column(primary_key=True)
    col: Mapped[a]
""",
        )
        assert _field(entities, "col").index


class TestModuleScopeEdges:
    ALIAS = (
        "from typing import Annotated\n"
        "from sqlalchemy.orm import mapped_column\n\n"
        "intpk = Annotated[int, mapped_column(primary_key=True)]\n"
    )

    def _model(self, head: str) -> str:
        return (
            head
            + HEADER
            + "\nclass Account(Base):\n    __tablename__ = 'account'\n    id: Mapped[intpk]\n"
        )

    def _parse_tree(self, tmp_path: Path) -> dict[str, EntityInfo]:
        entities, _ = parse_models_directory(tmp_path, include_patterns=["**/*.py"])
        return entities

    def test_two_level_relative_import(self, tmp_path: Path):
        (tmp_path / "pkg" / "sub").mkdir(parents=True)
        (tmp_path / "pkg" / "types.py").write_text(self.ALIAS, encoding="utf-8")
        (tmp_path / "pkg" / "sub" / "models.py").write_text(
            self._model("from ..types import intpk\n"), encoding="utf-8"
        )
        assert _field(self._parse_tree(tmp_path), "id").is_primary_key

    def test_unresolvable_relative_import_is_not_an_alias(self, tmp_path: Path):
        (tmp_path / "types.py").write_text(self.ALIAS, encoding="utf-8")
        (tmp_path / "models.py").write_text(
            self._model("from .missing import intpk\n"), encoding="utf-8"
        )
        assert _field(self._parse_tree(tmp_path), "id").type_str == "intpk"

    def test_star_import_picks_its_module_among_conflicting_ones(self, tmp_path: Path):
        (tmp_path / "types.py").write_text(self.ALIAS, encoding="utf-8")
        (tmp_path / "other.py").write_text(
            self.ALIAS.replace("primary_key=True", "index=True"), encoding="utf-8"
        )
        (tmp_path / "models.py").write_text(self._model("from .types import *\n"), encoding="utf-8")
        f = _field(self._parse_tree(tmp_path), "id")
        assert (f.is_primary_key, f.index) == (True, False)

    def test_aliases_in_several_model_modules(self, tmp_path: Path):
        (tmp_path / "types.py").write_text(self.ALIAS, encoding="utf-8")
        (tmp_path / "a.py").write_text(self._model(""), encoding="utf-8")
        (tmp_path / "b.py").write_text(
            self._model("").replace("Account", "Other").replace("'account'", "'other'"),
            encoding="utf-8",
        )
        entities = self._parse_tree(tmp_path)
        assert entities["Account"].fields[0].is_primary_key
        assert entities["Other"].fields[0].is_primary_key

    @pytest.mark.skipif(sys.version_info < (3, 12), reason="`type X = ...` needs Python 3.12")
    def test_pep695_type_statement_rebinds_the_name(self, tmp_path: Path):
        (tmp_path / "models.py").write_text(
            self._model(
                self.ALIAS + "type intpk = Annotated[int, mapped_column(primary_key=True)]\n"
            ),
            encoding="utf-8",
        )
        assert _field(self._parse_tree(tmp_path), "id").type_str == "intpk"


def test_resolver_without_a_file_uses_unique_aliases():
    import ast as _ast

    from erdify.parser.aliases import AliasResolver

    tree = _ast.parse("intpk = Annotated[int, mapped_column(primary_key=True)]\n")
    resolver = AliasResolver({Path("types.py"): tree}, classes=[])
    assert set(resolver.aliases_for(None)) == {"intpk"}


class TestPythonScoping:
    """Review fixes: Python's own name semantics (#249, #250)."""

    ALIAS = (
        "from typing import Annotated\n"
        "from sqlalchemy.orm import mapped_column\n\n"
        "intpk = Annotated[int, mapped_column(primary_key=True)]\n"
    )

    def _model(self, head: str, body: str = "    id: Mapped[intpk]\n", tail: str = "") -> str:
        return (
            head + HEADER + "\nclass Account(Base):\n    __tablename__ = 'account'\n" + body + tail
        )

    def _parse_tree(self, root: Path) -> dict[str, EntityInfo]:
        entities, _ = parse_models_directory(root, include_patterns=["**/*.py"])
        return entities

    def test_relative_input_path_with_package_import(self, tmp_path: Path, monkeypatch):
        """`erdify .` on a module with `from . import db` must not crash."""
        (tmp_path / "models.py").write_text(
            self._model("from . import db\n" + self.ALIAS), encoding="utf-8"
        )
        monkeypatch.chdir(tmp_path)
        entities, _ = parse_models_directory(Path("."))
        assert _field(entities, "id").is_primary_key

    def test_absolute_import_of_a_scanned_module(self, tmp_path: Path):
        (tmp_path / "coltypes.py").write_text(self.ALIAS, encoding="utf-8")
        (tmp_path / "models.py").write_text(
            self._model("from coltypes import intpk\n"), encoding="utf-8"
        )
        assert _field(self._parse_tree(tmp_path), "id").is_primary_key

    def test_ambiguous_absolute_import_prefers_its_own_package(self, tmp_path: Path):
        for svc, flag in (("svc1", "primary_key=True"), ("svc2", "index=True")):
            (tmp_path / svc / "app" / "users").mkdir(parents=True)
            (tmp_path / svc / "app" / "coltypes.py").write_text(
                self.ALIAS.replace("primary_key=True", flag), encoding="utf-8"
            )
        (tmp_path / "svc1" / "app" / "users" / "models.py").write_text(
            self._model("from app.coltypes import intpk\n"), encoding="utf-8"
        )
        f = _field(self._parse_tree(tmp_path), "id")
        assert (f.is_primary_key, f.index) == (True, False)

    def test_still_ambiguous_import_falls_back_by_name(self, tmp_path: Path):
        """`coltypes` at the top and in `pkg/` both fit `pkg/models.py`: by name."""
        (tmp_path / "pkg").mkdir()
        (tmp_path / "coltypes.py").write_text(self.ALIAS, encoding="utf-8")
        (tmp_path / "pkg" / "coltypes.py").write_text(self.ALIAS, encoding="utf-8")
        (tmp_path / "pkg" / "models.py").write_text(
            self._model("from coltypes import intpk\n"), encoding="utf-8"
        )
        assert _field(self._parse_tree(tmp_path), "id").is_primary_key

    def test_module_outside_the_import_root_is_not_imported(self, tmp_path: Path):
        """A scanned `unrelated_pkg/uuid.py` is not what `from uuid import UUID` imports."""
        (tmp_path / "unrelated_pkg").mkdir()
        (tmp_path / "unrelated_pkg" / "uuid.py").write_text(
            self.ALIAS.replace("intpk", "UUID"), encoding="utf-8"
        )
        (tmp_path / "models.py").write_text(
            self._model(
                "from uuid import UUID\n",
                "    id: Mapped[int] = mapped_column(primary_key=True)\n    token: Mapped[UUID]\n",
            ),
            encoding="utf-8",
        )
        token = _field(self._parse_tree(tmp_path), "token")
        assert (token.type_str, token.is_primary_key) == ("UUID", False)

    def test_absolute_import_with_a_relative_scan_root(self, tmp_path: Path, monkeypatch):
        """`erdify .` inside `app/` still resolves `from app.coltypes import intpk`."""
        (tmp_path / "app").mkdir()
        (tmp_path / "app" / "coltypes.py").write_text(self.ALIAS, encoding="utf-8")
        (tmp_path / "app" / "models.py").write_text(
            self._model("from app.coltypes import intpk as Key\n", "    id: Mapped[Key]\n"),
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path / "app")
        entities, _ = parse_models_directory(Path("."), include_patterns=["*.py"])
        assert _field(entities, "id").is_primary_key

    def test_circular_star_imports_keep_their_bindings(self, tmp_path: Path):
        (tmp_path / "a.py").write_text(self.ALIAS + "from .b import *\n", encoding="utf-8")
        (tmp_path / "b.py").write_text("from .a import *\n", encoding="utf-8")
        (tmp_path / "models.py").write_text(
            self._model("from .a import *\nfrom .b import intpk as Key\n", "    id: Mapped[Key]\n"),
            encoding="utf-8",
        )
        assert _field(self._parse_tree(tmp_path), "id").is_primary_key

    def test_bare_all_annotation_does_not_reset_all(self, tmp_path: Path):
        (tmp_path / "coltypes.py").write_text(
            self.ALIAS + "__all__ = []\n__all__: list[str]\n", encoding="utf-8"
        )
        (tmp_path / "models.py").write_text(
            self._model(
                "intpk = int\nfrom .coltypes import *\n",
                "    id: Mapped[int] = mapped_column(primary_key=True)\n    col: Mapped[intpk]\n",
            ),
            encoding="utf-8",
        )
        assert _field(self._parse_tree(tmp_path), "col").type_str == "intpk"

    def test_star_import_of_a_non_alias_blocks_the_fallback(self, tmp_path: Path):
        (tmp_path / "coltypes.py").write_text(self.ALIAS.replace("intpk", "UUID"), encoding="utf-8")
        (tmp_path / "common.py").write_text("from uuid import UUID\n", encoding="utf-8")
        (tmp_path / "models.py").write_text(
            self._model(
                "from .common import *\n",
                "    id: Mapped[int] = mapped_column(primary_key=True)\n    token: Mapped[UUID]\n",
            ),
            encoding="utf-8",
        )
        token = _field(self._parse_tree(tmp_path), "token")
        assert (token.type_str, token.is_primary_key) == ("UUID", False)

    def test_later_star_import_wins(self, tmp_path: Path):
        (tmp_path / "base_types.py").write_text(
            self.ALIAS.replace("primary_key=True", "index=True"), encoding="utf-8"
        )
        (tmp_path / "overrides.py").write_text(self.ALIAS, encoding="utf-8")
        (tmp_path / "models.py").write_text(
            self._model("from .base_types import *\nfrom .overrides import *\n"),
            encoding="utf-8",
        )
        f = _field(self._parse_tree(tmp_path), "id")
        assert (f.is_primary_key, f.index) == (True, False)

    def test_star_import_after_a_local_binding_overrides_it(self, tmp_path: Path):
        (tmp_path / "coltypes.py").write_text(self.ALIAS, encoding="utf-8")
        (tmp_path / "models.py").write_text(
            self._model("intpk = int\nfrom .coltypes import *\n"), encoding="utf-8"
        )
        assert _field(self._parse_tree(tmp_path), "id").is_primary_key

    def test_transitive_star_import_and_all(self, tmp_path: Path):
        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "columns.py").write_text(
            self.ALIAS + "_hidden = Annotated[int, mapped_column(index=True)]\n", encoding="utf-8"
        )
        (tmp_path / "pkg" / "__init__.py").write_text(
            "from .columns import *\n__all__ = ['intpk']\n", encoding="utf-8"
        )
        (tmp_path / "models.py").write_text(
            self._model(
                "from .pkg import *\n", "    id: Mapped[intpk]\n    other: Mapped[_hidden]\n"
            ),
            encoding="utf-8",
        )
        entities = self._parse_tree(tmp_path)
        assert _field(entities, "id").is_primary_key
        # `_hidden` is private to columns.py; only the by-name fallback finds it.
        assert _field(entities, "other").index

    def test_plain_re_export_is_an_alias(self, tmp_path: Path):
        (tmp_path / "coltypes.py").write_text(self.ALIAS + "UserId = intpk\n", encoding="utf-8")
        (tmp_path / "models.py").write_text(
            self._model("from .coltypes import UserId\n", "    id: Mapped[UserId]\n"),
            encoding="utf-8",
        )
        assert _flags(_field(self._parse_tree(tmp_path), "id")) == ("int", True, False, False, None)

    def test_rebinding_after_the_class_does_not_apply(self, tmp_path: Path):
        (tmp_path / "models.py").write_text(
            self._model(self.ALIAS, tail="\n\nintpk = int\n"), encoding="utf-8"
        )
        assert _field(self._parse_tree(tmp_path), "id").is_primary_key

    def test_class_in_an_unrelated_module_does_not_block_an_alias(self, tmp_path: Path):
        (tmp_path / "billing.py").write_text(
            HEADER + "\nclass Money(Base):\n    __tablename__ = 'money'\n"
            "    id: Mapped[int] = mapped_column(primary_key=True)\n",
            encoding="utf-8",
        )
        (tmp_path / "coltypes.py").write_text(
            self.ALIAS.replace(
                "intpk = Annotated[int, mapped_column(primary_key=True)]",
                "Money = Annotated[int, mapped_column(nullable=False)]",
            ),
            encoding="utf-8",
        )
        (tmp_path / "shop.py").write_text(
            self._model(
                "from .coltypes import Money\n",
                "    id: Mapped[int] = mapped_column(primary_key=True)\n"
                "    total: Mapped[Money | None]\n",
            ),
            encoding="utf-8",
        )
        assert _field(self._parse_tree(tmp_path), "total").is_nullable is False

    def test_mixin_in_another_module_uses_its_own_aliases(self, tmp_path: Path):
        (tmp_path / "mixins.py").write_text(
            self.ALIAS + "from sqlalchemy.orm import Mapped\n\n\n"
            "class KeyMixin:\n    id: Mapped[intpk]\n",
            encoding="utf-8",
        )
        (tmp_path / "models.py").write_text(
            "from .mixins import KeyMixin\n"
            + HEADER.replace("class User(Base):", "class Unused(Base):")
            + "\nintpk = int\n\n\n"
            "class Account(KeyMixin, Base):\n    __tablename__ = 'account'\n"
            "    name: Mapped[str] = mapped_column()\n",
            encoding="utf-8",
        )
        assert _field(self._parse_tree(tmp_path), "id").is_primary_key


def test_star_import_from_an_unscanned_module_binds_nothing(tmp_path: Path):
    entities = _parse(
        tmp_path,
        """
from os.path import *
intpk = Annotated[int, mapped_column(primary_key=True)]


class Account(Base):
    __tablename__ = "account"
    id: Mapped[intpk]
""",
    )
    assert _field(entities, "id").is_primary_key


def test_shared_alias_resolved_once_for_many_classes(tmp_path: Path):
    body = "".join(
        f"\n\nclass M{i}(Base):\n    __tablename__ = 'm{i}'\n    id: Mapped[taggedpk]\n"
        for i in range(20)
    )
    entities = _parse(
        tmp_path,
        """
intpk = Annotated[int, mapped_column(primary_key=True)]
taggedpk = Annotated[intpk, "tag"]
"""
        + body,
    )
    assert all(entities[f"M{i}"].fields[0].is_primary_key for i in range(20))


def test_mutual_imports_do_not_loop(tmp_path: Path):
    (tmp_path / "a.py").write_text("from .b import intpk\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("from .a import intpk\n", encoding="utf-8")
    (tmp_path / "models.py").write_text(
        "from .a import intpk\n"
        + HEADER
        + "\nclass Account(Base):\n    __tablename__ = 'account'\n"
        "    id: Mapped[int] = mapped_column(primary_key=True)\n    col: Mapped[intpk]\n",
        encoding="utf-8",
    )
    entities, _ = parse_models_directory(tmp_path, include_patterns=["*.py"])
    assert _field(entities, "col").type_str == "intpk"


class TestCopilotPr253:
    def test_last_all_assignment_counts(self, tmp_path: Path):
        """The last (annotated) __all__ exports nothing, so the star import keeps `intpk = int`."""
        (tmp_path / "coltypes.py").write_text(
            "from typing import Annotated\nfrom sqlalchemy.orm import mapped_column\n\n"
            "intpk = Annotated[int, mapped_column(primary_key=True)]\n"
            "__all__ = ['intpk']\n"
            "__all__: list[str] = []\n",
            encoding="utf-8",
        )
        (tmp_path / "models.py").write_text(
            "intpk = int\nfrom .coltypes import *\n"
            + HEADER
            + "\nclass Account(Base):\n    __tablename__ = 'account'\n"
            "    id: Mapped[int] = mapped_column(primary_key=True)\n    col: Mapped[intpk]\n",
            encoding="utf-8",
        )
        entities, _ = parse_models_directory(tmp_path, include_patterns=["*.py"])
        assert _field(entities, "col").type_str == "intpk"

    def test_alias_rebinding_itself_uses_the_earlier_binding(self, tmp_path: Path):
        entities = _parse(
            tmp_path,
            """
intpk = Annotated[int, mapped_column(primary_key=True)]
intpk = Annotated[intpk, "tag"]


class Account(Base):
    __tablename__ = "account"
    id: Mapped[intpk]
""",
        )
        assert _flags(_field(entities, "id")) == ("int", True, False, False, None)

    def test_resolved_alias_is_not_re_expanded_at_the_use_site(self, tmp_path: Path):
        (tmp_path / "keys.py").write_text(
            "from typing import Annotated\nfrom uuid import UUID\n"
            "from sqlalchemy.orm import mapped_column\n\n"
            "Key = Annotated[UUID, mapped_column(primary_key=True)]\n",
            encoding="utf-8",
        )
        (tmp_path / "models.py").write_text(
            "from .keys import Key\n"
            + HEADER
            + "\nUUID = Annotated[int, mapped_column(index=True)]\n\n\n"
            "class Account(Base):\n    __tablename__ = 'account'\n    id: Mapped[Key]\n",
            encoding="utf-8",
        )
        entities, _ = parse_models_directory(tmp_path, include_patterns=["*.py"])
        f = _field(entities, "id")
        assert (f.type_str, f.is_primary_key, f.index) == ("UUID", True, False)


class TestCopilotPr253Round3:
    ALIAS = TestPythonScoping.ALIAS

    def test_quoted_alias_base(self, tmp_path: Path):
        entities = _parse(
            tmp_path,
            """
intpk = Annotated[int, mapped_column(primary_key=True)]
indexedpk = Annotated["intpk", mapped_column(index=True)]


class Account(Base):
    __tablename__ = "account"
    id: Mapped[indexedpk]
""",
        )
        assert _flags(_field(entities, "id")) == ("int", True, False, False, None)

    @pytest.mark.parametrize(
        "head", ["from .coltypes import intpk\n", "from coltypes import intpk\n"]
    )
    def test_package_shadows_same_named_module(self, tmp_path: Path, head: str):
        (tmp_path / "coltypes").mkdir()
        (tmp_path / "coltypes" / "__init__.py").write_text(self.ALIAS, encoding="utf-8")
        (tmp_path / "coltypes.py").write_text(
            self.ALIAS.replace("primary_key=True", "index=True"), encoding="utf-8"
        )
        (tmp_path / "models.py").write_text(
            head + HEADER + "\nclass Account(Base):\n    __tablename__ = 'account'\n"
            "    id: Mapped[intpk]\n",
            encoding="utf-8",
        )
        entities, _ = parse_models_directory(tmp_path, include_patterns=["**/*.py"])
        f = _field(entities, "id")
        assert (f.is_primary_key, f.index) == (True, False)


class TestFallbackFixedPoint:
    """#254: the by-name fallback includes aliases that depend on it."""

    ALIAS = TestPythonScoping.ALIAS

    def test_derived_alias_through_an_ambiguous_import(self, tmp_path: Path):
        (tmp_path / "pkg").mkdir()
        (tmp_path / "coltypes.py").write_text(self.ALIAS, encoding="utf-8")
        (tmp_path / "pkg" / "coltypes.py").write_text(self.ALIAS, encoding="utf-8")
        (tmp_path / "pkg" / "derived.py").write_text(
            "from coltypes import intpk\nUserId = intpk\n", encoding="utf-8"
        )
        (tmp_path / "pkg" / "models.py").write_text(
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n    from .derived import UserId\n"
            + HEADER
            + "\nclass Account(Base):\n    __tablename__ = 'account'\n    id: Mapped[UserId]\n",
            encoding="utf-8",
        )
        entities, _ = parse_models_directory(tmp_path, include_patterns=["**/*.py"])
        assert _flags(_field(entities, "id")) == ("int", True, False, False, None)

    def test_chain_of_fallback_dependencies(self, tmp_path: Path):
        """Only the first link needs the fallback; the rest are imports of it."""
        (tmp_path / "pkg").mkdir()
        (tmp_path / "coltypes.py").write_text(self.ALIAS, encoding="utf-8")
        (tmp_path / "pkg" / "coltypes.py").write_text(self.ALIAS, encoding="utf-8")
        (tmp_path / "pkg" / "a.py").write_text(
            "from coltypes import intpk\nA = intpk\n", encoding="utf-8"
        )
        (tmp_path / "pkg" / "b.py").write_text("from .a import A\nB = A\n", encoding="utf-8")
        (tmp_path / "pkg" / "c.py").write_text("from .b import B\nC = B\n", encoding="utf-8")
        (tmp_path / "pkg" / "models.py").write_text(
            HEADER + "\nclass Account(Base):\n    __tablename__ = 'account'\n    id: Mapped[C]\n",
            encoding="utf-8",
        )
        entities, _ = parse_models_directory(tmp_path, include_patterns=["**/*.py"])
        assert _flags(_field(entities, "id")) == ("int", True, False, False, None)

    def _ambiguous_amb(self, tmp_path: Path) -> None:
        """Two identical `amb` modules that both fit `pkg/*`: imports from it are ambiguous."""
        (tmp_path / "pkg").mkdir(exist_ok=True)
        for path in (tmp_path / "amb.py", tmp_path / "pkg" / "amb.py"):
            path.write_text("", encoding="utf-8")

    def test_long_chain_is_not_cut_off(self, tmp_path: Path):
        (tmp_path / "pkg").mkdir()
        (tmp_path / "coltypes.py").write_text(self.ALIAS, encoding="utf-8")
        (tmp_path / "pkg" / "coltypes.py").write_text(self.ALIAS, encoding="utf-8")
        (tmp_path / "pkg" / "l0.py").write_text(
            "from coltypes import intpk\nX0 = intpk\n", encoding="utf-8"
        )
        for i in range(1, 15):
            (tmp_path / "pkg" / f"l{i}.py").write_text(
                f"from .l{i - 1} import X{i - 1}\nX{i} = X{i - 1}\n", encoding="utf-8"
            )
        (tmp_path / "pkg" / "models.py").write_text(
            HEADER + "\nclass Account(Base):\n    __tablename__ = 'account'\n    id: Mapped[X14]\n",
            encoding="utf-8",
        )
        entities, _ = parse_models_directory(tmp_path, include_patterns=["**/*.py"])
        assert _field(entities, "id").is_primary_key

    def test_conflicting_cycle_is_deterministic(self, tmp_path: Path):
        """The configuration that made a round-based fixed point oscillate."""
        self._ambiguous_amb(tmp_path)
        files = {
            "f1.py": self.ALIAS.replace("intpk", "B"),
            "f2.py": "from typing import Annotated\nfrom sqlalchemy.orm import mapped_column\n"
            "from amb import A\nB = Annotated[A, mapped_column(index=True)]\n",
            "f3.py": "from amb import B\nA = B\n",
        }
        for name, text in files.items():
            (tmp_path / "pkg" / name).write_text(text, encoding="utf-8")
        (tmp_path / "pkg" / "models.py").write_text(
            HEADER + "\nclass Account(Base):\n    __tablename__ = 'account'\n"
            "    id: Mapped[int] = mapped_column(primary_key=True)\n"
            "    a: Mapped[A]\n    b: Mapped[B]\n",
            encoding="utf-8",
        )
        results = set()
        for reverse in (False, True):
            entities = _parse_in_order(tmp_path, reverse=reverse)
            results.add(
                tuple(_flags(_field(entities, n)) + (_field(entities, n).index,) for n in "ab")
            )
        assert len(results) == 1  # same output whatever the file order
        (a, b) = next(iter(results))
        assert a[1] is False and b[1] is False  # conflicting definitions: no false PK

    def test_conflicting_cycle_through_an_explicit_import(self, tmp_path: Path):
        """`from .f2 import B` must not get a primary key the fallback would reject."""
        self.test_conflicting_cycle_is_deterministic(tmp_path)
        (tmp_path / "pkg" / "models.py").write_text(
            "from .f2 import B\n"
            + HEADER
            + "\nclass Account(Base):\n    __tablename__ = 'account'\n"
            "    id: Mapped[int] = mapped_column(primary_key=True)\n    b: Mapped[B]\n",
            encoding="utf-8",
        )
        for reverse in (False, True):
            b = _field(_parse_in_order(tmp_path, reverse=reverse), "b")
            assert b.is_primary_key is False

    def test_re_exports_of_an_ambiguous_alias(self, tmp_path: Path):
        """Many `intpk = _intpk` re-exports agree with the source and stay fast."""
        (tmp_path / "pkg").mkdir()
        (tmp_path / "coltypes.py").write_text(self.ALIAS, encoding="utf-8")
        (tmp_path / "pkg" / "coltypes.py").write_text(self.ALIAS, encoding="utf-8")
        for i in range(12):
            (tmp_path / "pkg" / f"re{i}.py").write_text(
                "from coltypes import intpk as _intpk\nintpk = _intpk\n", encoding="utf-8"
            )
        (tmp_path / "pkg" / "models.py").write_text(
            HEADER
            + "\nclass Account(Base):\n    __tablename__ = 'account'\n    id: Mapped[intpk]\n",
            encoding="utf-8",
        )
        entities, _ = parse_models_directory(tmp_path, include_patterns=["**/*.py"])
        assert _flags(_field(entities, "id")) == ("int", True, False, False, None)

    def test_ambiguous_import_of_a_class_name_is_not_an_alias(self, tmp_path: Path):
        self._ambiguous_amb(tmp_path)
        (tmp_path / "pkg" / "models.py").write_text(
            "from amb import User\n"
            + HEADER
            + "\nclass Account(Base):\n    __tablename__ = 'account'\n"
            "    id: Mapped[int] = mapped_column(primary_key=True)\n    col: Mapped[User]\n",
            encoding="utf-8",
        )
        entities, _ = parse_models_directory(tmp_path, include_patterns=["**/*.py"])
        assert _field(entities, "col").type_str == "User"


def _parse_in_order(root: Path, *, reverse: bool) -> dict[str, EntityInfo]:
    """Parse ``root`` with the discovered files in sorted or reversed order."""
    from unittest.mock import patch

    from erdify.parser import core

    real = core.discover_model_files

    def discover(*args, **kwargs):
        found = real(*args, **kwargs)
        if reverse:
            found.files.reverse()
        return found

    with patch.object(core, "discover_model_files", discover):
        entities, _ = parse_models_directory(root, include_patterns=["**/*.py"])
    return entities


def test_self_referencing_definition_that_differs_conflicts(tmp_path: Path):
    """`intpk = Annotated[_intpk, index]` over an ambiguous `intpk` is a different alias."""
    alias = TestPythonScoping.ALIAS
    (tmp_path / "pkg").mkdir()
    (tmp_path / "coltypes.py").write_text(alias, encoding="utf-8")
    (tmp_path / "pkg" / "coltypes.py").write_text(alias, encoding="utf-8")
    (tmp_path / "pkg" / "indexed.py").write_text(
        "from typing import Annotated\nfrom sqlalchemy.orm import mapped_column\n"
        "from coltypes import intpk as _intpk\n"
        "intpk = Annotated[_intpk, mapped_column(index=True)]\n",
        encoding="utf-8",
    )
    (tmp_path / "pkg" / "models.py").write_text(
        HEADER + "\nclass Account(Base):\n    __tablename__ = 'account'\n    id: Mapped[intpk]\n",
        encoding="utf-8",
    )
    entities, _ = parse_models_directory(tmp_path, include_patterns=["**/*.py"])
    # Two different `intpk` definitions: the by-name fallback does not guess.
    assert _field(entities, "id").type_str == "intpk"


class TestAmbiguousImportCandidates:
    """An ambiguous import consults only the modules it could name (#254 review)."""

    ALIAS = TestPythonScoping.ALIAS

    def _layout(self, tmp_path: Path, models: dict[str, str]) -> dict[str, EntityInfo]:
        (tmp_path / "pkg").mkdir()
        (tmp_path / "coltypes.py").write_text(self.ALIAS, encoding="utf-8")
        (tmp_path / "pkg" / "coltypes.py").write_text(self.ALIAS, encoding="utf-8")
        (tmp_path / "pkg" / "re0.py").write_text(
            "from coltypes import intpk as _intpk\nintpk = _intpk\n", encoding="utf-8"
        )
        for name, text in models.items():
            (tmp_path / "pkg" / name).write_text(text, encoding="utf-8")
        entities, _ = parse_models_directory(tmp_path, include_patterns=["**/*.py"])
        return entities

    @staticmethod
    def _model(cls: str, head: str) -> str:
        return (
            head
            + HEADER.replace("class User(Base):", f"class _{cls}User(Base):")
            + f"\nclass {cls}(Base):\n    __tablename__ = '{cls.lower()}'\n    id: Mapped[intpk]\n"
        )

    @pytest.mark.parametrize("order", [("a.py", "b.py"), ("b.py", "a.py")])
    def test_cold_explicit_import_of_a_re_export(self, tmp_path: Path, order: tuple[str, str]):
        explicit, unbound = order
        entities = self._layout(
            tmp_path,
            {
                explicit: self._model("Explicit", "from .re0 import intpk\n"),
                unbound: self._model("Unbound", ""),
            },
        )
        for cls in ("Explicit", "Unbound"):
            field = next(f for f in entities[cls].fields if f.name == "id")
            assert (field.type_str, field.is_primary_key) == ("int", True)

    def test_candidate_without_the_alias_makes_it_unknown(self, tmp_path: Path):
        (tmp_path / "pkg").mkdir()
        (tmp_path / "coltypes.py").write_text(self.ALIAS, encoding="utf-8")
        (tmp_path / "pkg" / "coltypes.py").write_text("intpk = int\n", encoding="utf-8")
        (tmp_path / "pkg" / "models.py").write_text(
            "from coltypes import intpk\n" + self._model("Account", ""),
            encoding="utf-8",
        )
        entities, _ = parse_models_directory(tmp_path, include_patterns=["**/*.py"])
        assert next(f for f in entities["Account"].fields if f.name == "id").type_str == "intpk"
