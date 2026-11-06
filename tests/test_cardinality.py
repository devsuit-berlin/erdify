"""End-to-end tests for FK cardinality and PK nullability (#216, #217, #218).

Each test parses real model source, so it covers both the parser (which
populates ``is_nullable`` / ``is_unique``) and the generator (which turns
them into crow's-foot glyphs).
"""

import json
from pathlib import Path

import pytest

from erdify.generator import generate_json, generate_mermaid, generate_plantuml
from erdify.parser import parse_models_directory

SQLMODEL_216 = """
from sqlmodel import Field, SQLModel


class Team(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str


class Member(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    team_id: int | None = Field(default=None, foreign_key="team.id")
    mentor_id: int = Field(foreign_key="team.id")
"""

SQLMODEL_218 = """
from sqlmodel import Field, SQLModel


class Account(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)


class Profile(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    account_id: int = Field(foreign_key="account.id", unique=True)
"""

SQLALCHEMY_TABLE_ARGS = """
from sqlalchemy import ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "account"
    id: Mapped[int] = mapped_column(primary_key=True)


class Profile(Base):
    __tablename__ = "profile"
    __table_args__ = (UniqueConstraint("account_id"), {"schema": "app"})
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"))


class Wallet(Base):
    __tablename__ = "wallet"
    __table_args__ = (Index("ix_wallet_account", "account_id", unique=True),)
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("account.id"))


class Login(Base):
    __tablename__ = "login"
    __table_args__ = (
        UniqueConstraint("account_id", "provider"),
        Index("ix_login_account", "account_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"))
    provider: Mapped[str]


class Badge(Base):
    __tablename__ = "badge"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"), unique=True)
"""

DJANGO = """
from django.db import models


class Account(models.Model):
    pass


class Profile(models.Model):
    account = models.ForeignKey(Account, on_delete=models.CASCADE, unique=True)
    referrer = models.ForeignKey(Account, on_delete=models.SET_NULL, null=True)
    slug = models.SlugField(unique=True)
"""


def _parse(tmp_path: Path, source: str) -> dict:
    (tmp_path / "models.py").write_text(source)
    entities, _ = parse_models_directory(tmp_path)
    return entities


def _field(entities: dict, entity: str, name: str):
    return next(f for f in entities[entity].fields if f.name == name)


class TestNullableForeignKey:
    """#216: a nullable FK is optional on the referenced side."""

    def test_mermaid(self, tmp_path: Path):
        out = generate_mermaid(_parse(tmp_path, SQLMODEL_216))
        assert 'Member }o--o| Team : "team_id"' in out
        assert 'Member }o--|| Team : "mentor_id"' in out

    def test_plantuml(self, tmp_path: Path):
        out = generate_plantuml(_parse(tmp_path, SQLMODEL_216))
        assert 'Member }o--o| Team : "team_id"' in out
        assert 'Member }o--|| Team : "mentor_id"' in out

    def test_explicit_nullable_overrides_annotation(self, tmp_path: Path):
        src = (
            SQLALCHEMY_TABLE_ARGS
            + """

class Note(Base):
    __tablename__ = "note"
    id: Mapped[int] = mapped_column(primary_key=True)
    a_id: Mapped[int] = mapped_column(ForeignKey("account.id"), nullable=True)
    b_id: Mapped[int | None] = mapped_column(ForeignKey("account.id"), nullable=False)
"""
        )
        entities = _parse(tmp_path, src)
        assert _field(entities, "Note", "a_id").is_nullable
        assert not _field(entities, "Note", "b_id").is_nullable
        out = generate_mermaid(entities)
        assert 'Note }o--o| Account : "a_id"' in out
        assert 'Note }o--|| Account : "b_id"' in out

    def test_nullable_none_keeps_annotation(self, tmp_path: Path):
        """nullable=None is SQLAlchemy's "unspecified": the annotation decides."""
        src = (
            SQLALCHEMY_TABLE_ARGS
            + """

class Memo(Base):
    __tablename__ = "memo"
    id: Mapped[int] = mapped_column(primary_key=True)
    a_id: Mapped[int | None] = mapped_column(ForeignKey("account.id"), nullable=None)
"""
        )
        entities = _parse(tmp_path, src)
        assert _field(entities, "Memo", "a_id").is_nullable
        assert 'Memo }o--o| Account : "a_id"' in generate_mermaid(entities)

    def test_django_null_fk(self, tmp_path: Path):
        out = generate_mermaid(_parse(tmp_path, DJANGO))
        assert 'Profile }o--o| Account : "referrer_id"' in out


class TestPrimaryKeyNotNullable:
    """#217: an Optional primary key is never rendered as nullable."""

    def test_ir(self, tmp_path: Path):
        pk = _field(_parse(tmp_path, SQLMODEL_216), "Team", "id")
        assert pk.is_primary_key
        assert not pk.is_nullable
        assert pk.default_value is None

    def test_mermaid(self, tmp_path: Path):
        out = generate_mermaid(_parse(tmp_path, SQLMODEL_216))
        assert "        int id PK\n" in out
        assert "nullable, default None" in out  # still shown for the real FK
        assert 'int id PK "' not in out

    def test_plantuml(self, tmp_path: Path):
        out = generate_plantuml(_parse(tmp_path, SQLMODEL_216))
        assert "primary_key(id) : int\n" in out
        assert "foreign_key(team_id) : int? = None" in out

    def test_json(self, tmp_path: Path):
        doc = json.loads(generate_json(_parse(tmp_path, SQLMODEL_216)))
        fields = {(e["name"], f["name"]): f for e in doc["entities"] for f in e["fields"]}
        assert (fields["Team", "id"]["nullable"], fields["Team", "id"]["default"]) == (
            False,
            None,
        )
        assert fields["Member", "team_id"]["nullable"] is True

    def test_non_none_pk_default_is_kept(self, tmp_path: Path):
        src = (
            "import uuid\nfrom sqlmodel import Field, SQLModel\n\n"
            "class Doc(SQLModel, table=True):\n"
            "    id: uuid.UUID | None = Field(default_factory=uuid.uuid4, primary_key=True)\n"
            "    code: str = Field(default='x', primary_key=False)\n"
        )
        entities = _parse(tmp_path, src)
        assert not _field(entities, "Doc", "id").is_nullable
        assert _field(entities, "Doc", "code").default_value is not None


class TestUniqueForeignKey:
    """#218: a unique FK is a 1:1 relationship."""

    def test_sqlmodel_field_unique(self, tmp_path: Path):
        entities = _parse(tmp_path, SQLMODEL_218)
        assert _field(entities, "Profile", "account_id").is_unique
        out = generate_mermaid(entities)
        assert 'Profile |o--|| Account : "account_id"' in out
        assert "int account_id FK,UK" in out

    def test_unique_primary_key_is_not_flagged(self, tmp_path: Path):
        src = SQLMODEL_218.replace(
            "Field(default=None, primary_key=True)\n\n\nclass Profile",
            "Field(default=None, primary_key=True, unique=True)\n\n\nclass Profile",
        )
        assert not _field(_parse(tmp_path, src), "Account", "id").is_unique

    @pytest.mark.parametrize(
        ("entity", "expected"),
        [
            ("Profile", 'Profile |o--|| Account : "account_id"'),  # UniqueConstraint
            ("Wallet", 'Wallet |o--o| Account : "account_id"'),  # unique Index, nullable
            ("Badge", 'Badge |o--|| Account : "account_id"'),  # mapped_column(unique=True)
        ],
    )
    def test_sqlalchemy_unique_sources(self, tmp_path: Path, entity: str, expected: str):
        entities = _parse(tmp_path, SQLALCHEMY_TABLE_ARGS)
        assert _field(entities, entity, "account_id").is_unique
        assert expected in generate_mermaid(entities)

    def test_composite_constraint_and_non_unique_index_ignored(self, tmp_path: Path):
        entities = _parse(tmp_path, SQLALCHEMY_TABLE_ARGS)
        assert not _field(entities, "Login", "account_id").is_unique
        assert not _field(entities, "Login", "provider").is_unique
        assert 'Login }o--|| Account : "account_id"' in generate_mermaid(entities)

    def test_partial_unique_index_is_not_one_to_one(self, tmp_path: Path):
        src = SQLALCHEMY_TABLE_ARGS.replace(
            'Index("ix_wallet_account", "account_id", unique=True)',
            'Index("ix_wallet_account", "account_id", unique=True, '
            'postgresql_where=text("deleted_at IS NULL"))',
        )
        entities = _parse(tmp_path, src)
        assert not _field(entities, "Wallet", "account_id").is_unique
        assert 'Wallet }o--o| Account : "account_id"' in generate_mermaid(entities)

    def test_annotated_table_args(self, tmp_path: Path):
        src = SQLALCHEMY_TABLE_ARGS.replace(
            '__table_args__ = (UniqueConstraint("account_id"), {"schema": "app"})',
            '__table_args__: tuple = (UniqueConstraint("account_id"),)',
        )
        assert _field(_parse(tmp_path, src), "Profile", "account_id").is_unique

    def test_django_unique(self, tmp_path: Path):
        entities = _parse(tmp_path, DJANGO)
        assert _field(entities, "Profile", "account_id").is_unique
        assert _field(entities, "Profile", "slug").is_unique
        assert 'Profile |o--|| Account : "account_id"' in generate_mermaid(entities)


class TestPrimaryKeyNotNullableAcrossSources:
    """#217 for the other ORM sources, and its deliberate limit to ORM models."""

    def test_sqlalchemy_optional_pk(self, tmp_path: Path):
        src = (
            "from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column\n\n"
            "class Base(DeclarativeBase):\n    pass\n\n"
            "class Item(Base):\n"
            "    __tablename__ = 'item'\n"
            "    id: Mapped[int | None] = mapped_column(primary_key=True, default=None)\n"
        )
        pk = _field(_parse(tmp_path, src), "Item", "id")
        assert (pk.is_nullable, pk.default_value) == (False, None)

    def test_django_null_pk(self, tmp_path: Path):
        src = (
            "from django.db import models\n\n"
            "class Item(models.Model):\n"
            "    code = models.CharField(primary_key=True, null=True)\n"
        )
        assert not _field(_parse(tmp_path, src), "Item", "code").is_nullable

    def test_inferred_pydantic_pk_keeps_optional(self, tmp_path: Path):
        """A DTO's `id: int | None = None` is genuinely optional; keep it."""
        (tmp_path / "models.py").write_text(
            "from pydantic import BaseModel\n\n"
            "class UserIn(BaseModel):\n"
            "    id: int | None = None\n"
            "    name: str\n"
        )
        entities, _ = parse_models_directory(tmp_path, infer_keys=True)
        pk = _field(entities, "UserIn", "id")
        assert pk.is_primary_key
        assert (pk.is_nullable, pk.default_value) == (True, "None")


class TestTableArgsForms:
    """#218: the syntactic forms __table_args__ uniqueness can take."""

    BASE = (
        "import sqlalchemy as sa\n"
        "from sqlalchemy import ForeignKey\n"
        "from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column\n\n"
        "class Base(DeclarativeBase):\n    pass\n\n"
        "class Account(Base):\n"
        "    __tablename__ = 'account'\n"
        "    id: Mapped[int] = mapped_column(primary_key=True)\n\n"
        "class Profile(Base):\n"
        "    __tablename__ = 'profile'\n"
        "    id: Mapped[int] = mapped_column(primary_key=True)\n"
        "    account_id: Mapped[int] = mapped_column(ForeignKey('account.id'))\n"
        "    __table_args__ = {args}\n"
    )

    @pytest.mark.parametrize(
        ("args", "unique"),
        [
            ("[sa.UniqueConstraint('account_id')]", True),  # list + attribute call
            ("(sa.Index('ix', 'account_id', unique=True),)", True),
            ("(sa.Index('ix', 'account_id', unique=False),)", False),
            ("{'schema': 'app'}", False),  # dict-only
            ("(sa.UniqueConstraint(account_id),)", True),  # bare column reference
            ("(sa.Index('ix', account_id, unique=True),)", True),
            ("(sa.Index('ix', 'account_id', unique=True, postgresql_where=None),)", True),
        ],
    )
    def test_forms(self, tmp_path: Path, args: str, unique: bool):
        entities = _parse(tmp_path, self.BASE.format(args=args))
        assert _field(entities, "Profile", "account_id").is_unique is unique

    def test_plantuml_renders_uk_and_one_to_one(self, tmp_path: Path):
        src = self.BASE.format(args="(sa.UniqueConstraint('account_id'),)")
        out = generate_plantuml(_parse(tmp_path, src))
        assert "foreign_key(account_id) : int UK" in out
        assert 'Profile |o--|| Account : "account_id"' in out


class TestExplicitColumnName:
    """#221: mapped_column("db_name", ...) sets the DB column name."""

    SRC = (
        "from sqlalchemy import ForeignKey, Index, UniqueConstraint\n"
        "from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column\n\n"
        "class Base(DeclarativeBase):\n    pass\n\n"
        "class Account(Base):\n"
        "    __tablename__ = 'account'\n"
        "    id: Mapped[int] = mapped_column(primary_key=True)\n\n"
        "class Profile(Base):\n"
        "    __tablename__ = 'profile'\n"
        "    __table_args__ = ({constraint},)\n"
        "    id: Mapped[int] = mapped_column(primary_key=True)\n"
        "    account: Mapped[int] = mapped_column('account_id', ForeignKey('account.id'))\n"
    )

    @pytest.mark.parametrize(
        "constraint",
        [
            "UniqueConstraint('account_id')",  # DB column name
            "UniqueConstraint(account)",  # bare reference names the attribute
            "Index('ix', 'account_id', unique=True)",
        ],
    )
    def test_constraint_matches_db_column_name(self, tmp_path: Path, constraint: str):
        entities = _parse(tmp_path, self.SRC.format(constraint=constraint))
        assert _field(entities, "Profile", "account").is_unique
        assert 'Profile |o--|| Account : "account"' in generate_mermaid(entities)

    def test_string_constraint_does_not_match_attribute_name(self, tmp_path: Path):
        """A string names the DB column; the attribute `account` has DB name account_id."""
        src = self.SRC.format(constraint="UniqueConstraint('account')")
        assert not _field(_parse(tmp_path, src), "Profile", "account").is_unique

    def test_db_name_collision_marks_only_the_owner(self, tmp_path: Path):
        src = self.SRC.format(constraint="UniqueConstraint('account')") + (
            "    legacy: Mapped[str] = mapped_column('account')\n"
        )
        entities = _parse(tmp_path, src)
        assert _field(entities, "Profile", "legacy").is_unique
        assert not _field(entities, "Profile", "account").is_unique

    @pytest.mark.parametrize(
        "decl",
        [
            "mapped_column(ForeignKey('account.id'), name='account_id')",
            "orm.mapped_column('account_id', ForeignKey('account.id'))",
            "orm.mapped_column('account_id', sa.ForeignKey('account.id'))",
        ],
    )
    def test_other_name_forms(self, tmp_path: Path, decl: str):
        src = self.SRC.format(constraint="UniqueConstraint('account_id')").replace(
            "mapped_column('account_id', ForeignKey('account.id'))", decl
        )
        src = "import sqlalchemy as sa\nfrom sqlalchemy import orm\n" + src
        entities = _parse(tmp_path, src)
        assert _field(entities, "Profile", "account").is_unique
        assert 'Profile |o--|| Account : "account"' in generate_mermaid(entities)

    def test_subclass_override_drops_inherited_name(self, tmp_path: Path):
        src = (
            "from sqlalchemy import ForeignKey, UniqueConstraint\n"
            "from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column\n\n"
            "class Base(DeclarativeBase):\n    pass\n\n"
            "class Account(Base):\n"
            "    __tablename__ = 'account'\n"
            "    id: Mapped[int] = mapped_column(primary_key=True)\n\n"
            "class AccountMixin:\n"
            "    account: Mapped[int] = mapped_column('account_id', ForeignKey('account.id'))\n\n"
            "class Profile(AccountMixin, Base):\n"
            "    __tablename__ = 'profile'\n"
            "    __table_args__ = (UniqueConstraint('account_id'),)\n"
            "    id: Mapped[int] = mapped_column(primary_key=True)\n"
            "    account: Mapped[int] = mapped_column(ForeignKey('account.id'))\n"
        )
        assert not _field(_parse(tmp_path, src), "Profile", "account").is_unique

    def test_key_takes_precedence(self, tmp_path: Path):
        """String constraints resolve through the column key (#221)."""
        src = self.SRC.format(constraint="UniqueConstraint('acct')").replace(
            "mapped_column('account_id', ForeignKey('account.id'))",
            "mapped_column('account_id', ForeignKey('account.id'), key='acct')",
        )
        assert _field(_parse(tmp_path, src), "Profile", "account").is_unique

    def test_diamond_override_clears_inherited_name(self, tmp_path: Path):
        src = (
            "from sqlalchemy import ForeignKey, UniqueConstraint\n"
            "from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column\n\n"
            "class Base(DeclarativeBase):\n    pass\n\n"
            "class Account(Base):\n"
            "    __tablename__ = 'account'\n"
            "    id: Mapped[int] = mapped_column(primary_key=True)\n\n"
            "class Root:\n"
            "    account: Mapped[int] = mapped_column('account_id', ForeignKey('account.id'))\n\n"
            "class Left(Root):\n    pass\n\n"
            "class Right(Root):\n"
            "    account: Mapped[int] = mapped_column(ForeignKey('account.id'))\n\n"
            "class Profile(Left, Right, Base):\n"
            "    __tablename__ = 'profile'\n"
            "    __table_args__ = (UniqueConstraint('account'),)\n"
            "    id: Mapped[int] = mapped_column(primary_key=True)\n"
        )
        assert _field(_parse(tmp_path, src), "Profile", "account").is_unique

    @pytest.mark.parametrize(
        "decl",
        [
            "Field(sa_column=Column('acct', ForeignKey('account.id')))",
            "Field(foreign_key='account.id', sa_column_kwargs={'name': 'acct'})",
            # an explicit key wins over the name
            "Field(foreign_key='account.id', sa_column_kwargs={'name': 'x', 'key': 'acct'})",
        ],
    )
    def test_sqlmodel_explicit_column_name(self, tmp_path: Path, decl: str):
        src = (
            "from sqlalchemy import Column, ForeignKey, UniqueConstraint\n"
            "from sqlmodel import Field, SQLModel\n\n"
            "class Account(SQLModel, table=True):\n"
            "    id: int = Field(primary_key=True)\n\n"
            "class Profile(SQLModel, table=True):\n"
            "    __table_args__ = (UniqueConstraint('acct'),)\n"
            "    id: int = Field(primary_key=True)\n"
            f"    account_id: int = {decl}\n"
        )
        assert _field(_parse(tmp_path, src), "Profile", "account_id").is_unique

    def test_column_name_is_not_a_default(self, tmp_path: Path):
        src = self.SRC.format(constraint="UniqueConstraint('account_id')")
        assert _field(_parse(tmp_path, src), "Profile", "account").default_value is None

    def test_inherited_column_name(self, tmp_path: Path):
        src = (
            "from sqlalchemy import ForeignKey, UniqueConstraint\n"
            "from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column\n\n"
            "class Base(DeclarativeBase):\n    pass\n\n"
            "class Account(Base):\n"
            "    __tablename__ = 'account'\n"
            "    id: Mapped[int] = mapped_column(primary_key=True)\n\n"
            "class AccountMixin:\n"
            "    account: Mapped[int] = mapped_column('account_id', ForeignKey('account.id'))\n\n"
            "class Profile(AccountMixin, Base):\n"
            "    __tablename__ = 'profile'\n"
            "    __table_args__ = (UniqueConstraint('account_id'),)\n"
            "    id: Mapped[int] = mapped_column(primary_key=True)\n"
        )
        assert _field(_parse(tmp_path, src), "Profile", "account").is_unique

    def test_sqlmodel_positional_default_is_kept(self, tmp_path: Path):
        src = (
            "from sqlmodel import Field, SQLModel\n\n"
            "class Item(SQLModel, table=True):\n"
            "    id: int = Field(primary_key=True)\n"
            "    status: str = Field('draft')\n"
        )
        assert _field(_parse(tmp_path, src), "Item", "status").default_value == "'draft'"


class TestSharedPrimaryKey:
    """#222: an FK that is the entity's only PK column is a 1:1."""

    SRC = """
from sqlmodel import Field, SQLModel


class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)


class UserProfile(SQLModel, table=True):
    id: int = Field(primary_key=True, foreign_key="user.id")


class OrderLine(SQLModel, table=True):
    user_id: int = Field(primary_key=True, foreign_key="user.id")
    line_no: int = Field(primary_key=True)
    note: str
"""

    def test_sole_pk_fk_is_one_to_one(self, tmp_path: Path):
        out = generate_mermaid(_parse(tmp_path, self.SRC))
        assert 'UserProfile |o--|| User : "id"' in out

    def test_composite_pk_fk_stays_many_to_one(self, tmp_path: Path):
        out = generate_plantuml(_parse(tmp_path, self.SRC))
        assert 'OrderLine }o--|| User : "user_id"' in out

    def test_sql_composite_pk_fk_stays_many_to_one(self, tmp_path: Path):
        pytest.importorskip("sqlglot")
        (tmp_path / "schema.sql").write_text(
            'CREATE TABLE "user" (id INTEGER PRIMARY KEY);\n'
            "CREATE TABLE line (\n"
            '  user_id INTEGER REFERENCES "user"(id), line_no INTEGER, note TEXT,\n'
            "  PRIMARY KEY (user_id, line_no));\n"
        )
        entities, _ = parse_models_directory(tmp_path, include_patterns=["*.sql"])
        assert "line }o--|| user" in generate_mermaid(entities)

    def test_sql_shared_primary_key(self, tmp_path: Path):
        pytest.importorskip("sqlglot")
        (tmp_path / "schema.sql").write_text(
            'CREATE TABLE "user" (id INTEGER PRIMARY KEY);\n'
            'CREATE TABLE profile (id INTEGER PRIMARY KEY REFERENCES "user"(id));\n'
        )
        entities, _ = parse_models_directory(tmp_path, include_patterns=["*.sql"])
        assert "profile |o--|| user" in generate_mermaid(entities)


class TestDjangoPrimaryKeyForeignKey:
    """#224: ForeignKey(primary_key=True) is the table's PK, with no implicit id."""

    SRC = """
from django.db import models


class Account(models.Model):
    pass


class Settings(models.Model):
    owner = models.ForeignKey(Account, on_delete=models.CASCADE, primary_key=True, null=True)
"""

    def test_fields(self, tmp_path: Path):
        entities = _parse(tmp_path, self.SRC)
        assert [f.name for f in entities["Settings"].fields] == ["owner_id"]
        owner = _field(entities, "Settings", "owner_id")
        assert owner.is_primary_key and owner.is_foreign_key
        assert not owner.is_nullable
        assert not owner.is_unique

    def test_drawn_one_to_one(self, tmp_path: Path):
        out = generate_mermaid(_parse(tmp_path, self.SRC))
        assert 'Settings |o--|| Account : "owner_id"' in out
        assert "int id PK" not in out.split("Settings {")[1]

    @pytest.mark.parametrize(
        "decl",
        [
            "models.ForeignKey(Account, on_delete=models.CASCADE, primary_key=True)",
            "models.OneToOneField(Account, on_delete=models.CASCADE, primary_key=True)",
        ],
    )
    def test_forms_and_json(self, tmp_path: Path, decl: str):
        src = self.SRC.replace(
            "models.ForeignKey(Account, on_delete=models.CASCADE, primary_key=True, null=True)",
            decl,
        )
        entities = _parse(tmp_path, src)
        assert entities["Settings"].relationships == []
        doc = json.loads(generate_json(entities))
        settings = next(e for e in doc["entities"] if e["name"] == "Settings")
        assert [(f["name"], f["primary_key"], f["foreign_key"]) for f in settings["fields"]] == [
            ("owner_id", True, True)
        ]
        assert 'Settings |o--|| Account : "owner_id"' in generate_mermaid(entities)

    def test_one_to_one_without_pk_is_a_unique_fk_column(self, tmp_path: Path):
        """A plain OneToOneField is a unique ``<name>_id`` column next to ``id`` (#223)."""
        src = self.SRC.replace(
            "models.ForeignKey(Account, on_delete=models.CASCADE, primary_key=True, null=True)",
            "models.OneToOneField(Account, on_delete=models.CASCADE)",
        )
        entities = _parse(tmp_path, src)
        assert [f.name for f in entities["Settings"].fields] == ["id", "owner_id"]
        assert entities["Settings"].relationships == []
        owner = _field(entities, "Settings", "owner_id")
        assert owner.is_foreign_key and owner.is_unique and not owner.is_primary_key


class TestDjangoInheritedOverride:
    """A subclass redeclaring a relationship attribute drops the inherited one."""

    BASE = """
from django.db import models


class Account(models.Model):
    pass


class Other(models.Model):
    pass


class OwnedBase(models.Model):
    owner = {base_decl}

    class Meta:
        abstract = True


class Settings(OwnedBase):
    owner = {sub_decl}
"""

    @pytest.mark.parametrize(
        ("base_decl", "sub_decl", "fields", "rels"),
        [
            (  # relationship -> PK FK column
                "models.OneToOneField(Account, on_delete=models.CASCADE)",
                "models.OneToOneField(Other, on_delete=models.CASCADE, primary_key=True)",
                ["owner_id"],
                [],
            ),
            (  # relationship -> FK column
                "models.OneToOneField(Account, on_delete=models.CASCADE)",
                "models.ForeignKey(Other, on_delete=models.CASCADE)",
                ["id", "owner_id"],
                [],
            ),
            (  # FK column -> 1:1 FK column to another target
                "models.ForeignKey(Account, on_delete=models.CASCADE)",
                "models.OneToOneField(Other, on_delete=models.CASCADE)",
                ["id", "owner_id"],
                [],
            ),
            (  # M:N relationship -> FK column
                "models.ManyToManyField(Account)",
                "models.ForeignKey(Other, on_delete=models.CASCADE)",
                ["id", "owner_id"],
                [],
            ),
            (  # FK column -> M:N relationship
                "models.ForeignKey(Account, on_delete=models.CASCADE)",
                "models.ManyToManyField(Other)",
                ["id"],
                [("Other", "many_to_many", "owner")],
            ),
        ],
    )
    def test_override(self, tmp_path: Path, base_decl, sub_decl, fields, rels):
        src = self.BASE.format(base_decl=base_decl, sub_decl=sub_decl)
        entities = _parse(tmp_path, src)
        settings = entities["Settings"]
        assert [f.name for f in settings.fields] == fields
        assert settings.relationships == rels
        out = generate_mermaid(entities)
        assert "Settings }o--|| Account" not in out
        assert "Settings ||--|| Account" not in out
        if "owner_id" in fields:
            fk = _field(entities, "Settings", "owner_id")
            assert fk.foreign_table and fk.foreign_table.startswith("other.")


class TestDjangoForeignKeyTarget:
    """#226: a Django FK column references the target's real PK or ``to_field``."""

    SRC = """
from django.db import models


class Account(models.Model):
    code = models.IntegerField(primary_key=True)
    slug = models.CharField(max_length=10, unique=True)


class Settings(models.Model):
    owner = models.OneToOneField(Account, on_delete=models.CASCADE, primary_key=True)


class Ref(models.Model):
    acc = models.ForeignKey(Account, on_delete=models.CASCADE)
    by_slug = models.ForeignKey(
        Account, on_delete=models.CASCADE, to_field="slug", related_name="by_slug"
    )
    settings = models.ForeignKey(Settings, on_delete=models.CASCADE)


class Plain(models.Model):
    pass


class ToPlain(models.Model):
    plain = models.ForeignKey(Plain, on_delete=models.CASCADE)
    external = models.ForeignKey("other_app.External", on_delete=models.CASCADE)
    unknown_field = models.ForeignKey(Plain, on_delete=models.CASCADE, to_field="nope")


class UuidBase(models.Model):
    uid = models.UUIDField(primary_key=True)

    class Meta:
        abstract = True


class Doc(UuidBase):
    pass


class Link(models.Model):
    doc = models.ForeignKey(Doc, on_delete=models.CASCADE)
"""

    def _fk(self, tmp_path: Path, entity: str, name: str):
        return _field(_parse(tmp_path, self.SRC), entity, name)

    def test_explicit_pk(self, tmp_path: Path):
        for entity, name in (("Settings", "owner_id"), ("Ref", "acc_id")):
            fk = self._fk(tmp_path, entity, name)
            assert fk.foreign_table == "account.code"
            assert fk.type_str == "int"

    def test_to_field(self, tmp_path: Path):
        fk = self._fk(tmp_path, "Ref", "by_slug_id")
        assert fk.foreign_table == "account.slug"
        assert fk.type_str == "str"

    def test_pk_that_is_a_foreign_key(self, tmp_path: Path):
        assert self._fk(tmp_path, "Ref", "settings_id").foreign_table == "settings.owner_id"

    def test_inherited_pk(self, tmp_path: Path):
        entities = _parse(tmp_path, self.SRC)
        fk = _field(entities, "Link", "doc_id")
        assert fk.foreign_table == "doc.uid"
        assert fk.type_str == _field(entities, "Doc", "uid").type_str

    def test_implicit_id_and_unknown_targets_fall_back(self, tmp_path: Path):
        entities = _parse(tmp_path, self.SRC)
        assert _field(entities, "ToPlain", "plain_id").foreign_table == "plain.id"
        assert _field(entities, "ToPlain", "external_id").foreign_table == "external.id"
        assert _field(entities, "ToPlain", "unknown_field_id").foreign_table == "plain.nope"

    def test_json(self, tmp_path: Path):
        doc = json.loads(generate_json(_parse(tmp_path, self.SRC)))
        settings = next(e for e in doc["entities"] if e["name"] == "Settings")
        assert settings["fields"][0]["foreign_table"] == "account.code"

    def test_cyclic_primary_keys_terminate(self, tmp_path: Path):
        src = """
from django.db import models


class A(models.Model):
    b = models.OneToOneField("B", on_delete=models.CASCADE, primary_key=True)


class B(models.Model):
    a = models.OneToOneField(A, on_delete=models.CASCADE, primary_key=True)
"""
        entities = _parse(tmp_path, src)
        assert _field(entities, "A", "b_id").foreign_table == "b.a_id"
        assert _field(entities, "B", "a_id").foreign_table == "a.b_id"

    def test_pk_with_unresolvable_target(self, tmp_path: Path):
        src = """
from django.db import models


class A(models.Model):
    b = models.OneToOneField(get_model(), on_delete=models.CASCADE, primary_key=True)


class C(models.Model):
    a = models.ForeignKey(A, on_delete=models.CASCADE)
"""
        assert _field(_parse(tmp_path, src), "C", "a_id").foreign_table == "a.b_id"

    def test_to_field_naming_a_foreign_key(self, tmp_path: Path):
        src = """
from django.db import models


class Account(models.Model):
    code = models.CharField(max_length=5, primary_key=True)


class Profile(models.Model):
    account = models.OneToOneField(Account, on_delete=models.CASCADE)


class Note(models.Model):
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, to_field="account")
"""
        fk = _field(_parse(tmp_path, src), "Note", "profile_id")
        assert fk.foreign_table == "profile.account_id"
        assert fk.type_str == "str"

    def test_type_follows_choices_enum(self, tmp_path: Path):
        src = """
from django.db import models


class Status(models.TextChoices):
    OPEN = "open"


class State(models.Model):
    code = models.CharField(max_length=5, primary_key=True, choices=Status.choices)


class Ticket(models.Model):
    state = models.ForeignKey(State, on_delete=models.CASCADE)
"""
        entities = _parse(tmp_path, src)
        assert _field(entities, "Ticket", "state_id").type_str == "Status"
        assert _field(entities, "State", "code").type_str == "Status"

    def test_key_through_another_column_of_the_same_model(self, tmp_path: Path):
        """Following a PK to another column of the same model is not a cycle."""
        src = """
from django.db import models


class Item(models.Model):
    code = models.CharField(max_length=5, unique=True)
    parent = models.OneToOneField(
        "self", on_delete=models.CASCADE, to_field="code", primary_key=True
    )


class Ref(models.Model):
    item = models.ForeignKey(Item, on_delete=models.CASCADE)
"""
        entities = _parse(tmp_path, src)
        assert _field(entities, "Item", "parent_id").type_str == "str"
        fk = _field(entities, "Ref", "item_id")
        assert fk.foreign_table == "item.parent_id"
        assert fk.type_str == "str"

    def test_removed_inherited_pk_falls_back_to_id(self, tmp_path: Path):
        """``code = None`` removes the inherited PK, so the target has the implicit ``id``."""
        src = """
from django.db import models


class Base(models.Model):
    code = models.CharField(max_length=5, primary_key=True)

    class Meta:
        abstract = True


class Item(Base):
    code = None


class Ref(models.Model):
    item = models.ForeignKey(Item, on_delete=models.CASCADE)
"""
        entities = _parse(tmp_path, src)
        assert [f.name for f in entities["Item"].fields] == ["id"]
        fk = _field(entities, "Ref", "item_id")
        assert fk.foreign_table == "item.id"
        assert fk.type_str == "int"


class TestDeclaredRelationshipNullability:
    """#223: 1:1 Django fields and keyless model references follow nullability."""

    DJANGO = """
from django.db import models


class Account(models.Model):
    pass


class Profile(models.Model):
    account = {decl}
"""

    @pytest.mark.parametrize(
        ("decl", "glyph"),
        [
            ("models.OneToOneField(Account, on_delete=models.CASCADE, null=True)", "|o--o|"),
            ("models.OneToOneField(Account, on_delete=models.CASCADE)", "|o--||"),
            # unique=False cannot turn a OneToOneField into N:1.
            ("models.OneToOneField(Account, on_delete=models.CASCADE, unique=False)", "|o--||"),
            (
                "models.ForeignKey(Account, on_delete=models.CASCADE, unique=True, null=True)",
                "|o--o|",
            ),
        ],
    )
    def test_django_one_to_one(self, tmp_path: Path, decl: str, glyph: str):
        entities = _parse(tmp_path, self.DJANGO.format(decl=decl))
        out = generate_mermaid(entities)
        assert f'Profile {glyph} Account : "account_id"' in out
        assert entities["Profile"].relationships == []
        assert _field(entities, "Profile", "account_id").is_unique

    def test_django_one_to_one_matches_unique_foreign_key(self, tmp_path: Path):
        """Two spellings of the same schema produce the same output."""
        o2o = generate_json(
            _parse(
                tmp_path,
                self.DJANGO.format(
                    decl="models.OneToOneField(Account, on_delete=models.CASCADE, null=True)"
                ),
            )
        )
        fk = generate_json(
            _parse(
                tmp_path,
                self.DJANGO.format(
                    decl="models.ForeignKey("
                    "Account, on_delete=models.CASCADE, unique=True, null=True)"
                ),
            )
        )
        assert o2o == fk

    KEYLESS = """
from pydantic import BaseModel


class User(BaseModel):
    id: int


class Post(BaseModel):
    id: int
    user: User | None
    tags: list[User] | None
"""

    KEYLESS_DATACLASS = """
from dataclasses import dataclass


@dataclass
class User:
    id: int


@dataclass
class Post:
    id: int
    user: User | None
    tags: list[User] | None
"""

    @pytest.mark.parametrize("src", [KEYLESS, KEYLESS_DATACLASS], ids=["pydantic", "dataclass"])
    def test_keyless_optional_reference(self, tmp_path: Path, src: str):
        entities = _parse(tmp_path, src)
        assert entities["Post"].nullable_relationships == ["user"]
        assert 'Post }o--o| User : "user"' in generate_mermaid(entities)

    @pytest.mark.parametrize(
        "annotation",
        [
            "User",
            "Optional[User]",
            '"User | None"',
            'Optional["User"]',
            # A model whose *name* contains "Optional" is still required.
            "OptionalUser",
        ],
    )
    def test_keyless_annotations(self, tmp_path: Path, annotation: str):
        src = f"""
from typing import Optional

from pydantic import BaseModel


class User(BaseModel):
    id: int


class OptionalUser(BaseModel):
    id: int


class Post(BaseModel):
    id: int
    user: {annotation}
"""
        entities = _parse(tmp_path, src)
        nullable = annotation not in ("User", "OptionalUser")
        target = "OptionalUser" if annotation == "OptionalUser" else "User"
        assert entities["Post"].nullable_relationships == (["user"] if nullable else [])
        glyph = "}o--o|" if nullable else "}o--||"
        assert f'Post {glyph} {target} : "user"' in generate_mermaid(entities)
        assert f'Post {glyph} {target} : "user"' in generate_plantuml(entities)

    def test_json_nullable_key(self, tmp_path: Path):
        src = self.KEYLESS
        doc = json.loads(generate_json(_parse(tmp_path, src)))
        post = next(e for e in doc["entities"] if e["name"] == "Post")
        assert {r["attribute"]: r["nullable"] for r in post["relationships"]} == {
            "user": True,
            "tags": False,
        }

    def test_exclude_drops_nullable_entry(self, tmp_path: Path):
        src = self.KEYLESS
        (tmp_path / "models.py").write_text(src)
        entities, _ = parse_models_directory(tmp_path, exclude_patterns=["User"])
        assert entities["Post"].relationships == []
        assert entities["Post"].nullable_relationships == []

    def test_sqlalchemy_relationship_nullable_in_json(self, tmp_path: Path):
        """``relationship()`` reads optionality from the annotation like model references."""
        src = """
from typing import List, Optional

from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Team(Base):
    __tablename__ = "team"
    id: Mapped[int] = mapped_column(primary_key=True)
    members: Mapped[List["Member"]] = relationship(back_populates="team")


class Member(Base):
    __tablename__ = "member"
    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[Optional[int]] = mapped_column(ForeignKey("team.id"))
    team: Mapped[Optional["Team"]] = relationship(back_populates="members")
"""
        entities = _parse(tmp_path, src)
        assert entities["Member"].nullable_relationships == ["team"]
        assert entities["Team"].nullable_relationships == []
        doc = json.loads(generate_json(entities))
        rels = {
            (e["name"], r["attribute"]): r["nullable"]
            for e in doc["entities"]
            for r in e["relationships"]
        }
        assert rels == {("Team", "members"): False, ("Member", "team"): True}
        # The FK column still draws the edge; the declared relationship adds none.
        out = generate_mermaid(entities)
        assert out.count("Member }o--o| Team") == 1

    def test_inherited_reference_follows_mro_winner(self, tmp_path: Path):
        src = """
from pydantic import BaseModel


class User(BaseModel):
    id: int


class Base(BaseModel):
    user: User | None


class Post(Base):
    id: int
    user: User
"""
        entities = _parse(tmp_path, src)
        assert entities["Post"].nullable_relationships == []
        assert 'Post }o--|| User : "user"' in generate_mermaid(entities)

    def test_django_fk_and_one_to_one_to_same_target(self, tmp_path: Path):
        """Both are FK columns now, so both edges are drawn."""
        src = """
from django.db import models


class Account(models.Model):
    pass


class Profile(models.Model):
    owner = models.ForeignKey(Account, on_delete=models.CASCADE)
    primary = models.OneToOneField(Account, on_delete=models.CASCADE, related_name="+")
"""
        out = generate_mermaid(_parse(tmp_path, src))
        assert 'Profile }o--|| Account : "owner_id"' in out
        assert 'Profile |o--|| Account : "primary_id"' in out


class TestEntityInfoPositional:
    """New ``EntityInfo`` fields go last, so pre-1.2 positional calls keep working."""

    def test_pre_1_2_positional_order(self):
        from erdify import EntityInfo

        e = EntityInfo("A", "a", [], [("B", "one", "b")], True, ["Base"], "django")
        assert e.is_link_table is True
        assert e.base_classes == ["Base"]
        assert e.source == "django"
        assert e.nullable_relationships == []
