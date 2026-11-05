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
        ],
    )
    def test_other_name_forms(self, tmp_path: Path, decl: str):
        src = self.SRC.format(constraint="UniqueConstraint('account_id')").replace(
            "mapped_column('account_id', ForeignKey('account.id'))", decl
        )
        src = "from sqlalchemy import orm\n" + src
        assert _field(_parse(tmp_path, src), "Profile", "account").is_unique

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

    def test_one_to_one_without_pk_is_unchanged(self, tmp_path: Path):
        """A plain OneToOneField is still a declared relationship (tracked in #223)."""
        src = self.SRC.replace(
            "models.ForeignKey(Account, on_delete=models.CASCADE, primary_key=True, null=True)",
            "models.OneToOneField(Account, on_delete=models.CASCADE)",
        )
        entities = _parse(tmp_path, src)
        assert [f.name for f in entities["Settings"].fields] == ["id"]
        assert entities["Settings"].relationships == [("Account", "one_to_one", "owner")]


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
            (  # FK column -> relationship
                "models.ForeignKey(Account, on_delete=models.CASCADE)",
                "models.OneToOneField(Other, on_delete=models.CASCADE)",
                ["id"],
                [("Other", "one_to_one", "owner")],
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
