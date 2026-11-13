import builtins
from pathlib import Path

import pytest

from erdify.parser import ModelParseError
from erdify.sql_parser import SqlDependencyError, SqlSchemaParser, discover_sql_files


def test_discover_sql_files_matches_include_and_skips_py(tmp_path: Path):
    (tmp_path / "schema.sql").write_text("CREATE TABLE a (id INT);")
    (tmp_path / "models.py").write_text("x = 1")
    sub = tmp_path / ".venv" / "pkg"
    sub.mkdir(parents=True)
    (sub / "vendor.sql").write_text("CREATE TABLE b (id INT);")

    found = discover_sql_files(tmp_path, ["*.sql"], [], use_default_excludes=True)

    assert [p.name for p in found] == ["schema.sql"]  # .py ignored, .venv pruned


def _parse_sql(tmp_path: Path, sql: str, **kw):  # type: ignore[no-untyped-def]
    f = tmp_path / "schema.sql"
    f.write_text(sql)
    return SqlSchemaParser([f], **kw).parse()


def test_create_table_columns_types_nullability_default(tmp_path: Path) -> None:
    entities, enums = _parse_sql(
        tmp_path,
        """
        CREATE TABLE app_user (
            id INTEGER PRIMARY KEY,
            email VARCHAR(255) NOT NULL,
            nickname VARCHAR(50),
            is_active BOOLEAN DEFAULT TRUE
        );
        """,
    )
    user = entities["app_user"]
    assert user.source == "sql"
    cols = {f.name: f for f in user.fields}
    assert cols["id"].is_primary_key is True
    assert cols["id"].is_nullable is False  # PRIMARY KEY implies NOT NULL (#217)
    assert cols["email"].is_nullable is False
    assert cols["nickname"].is_nullable is True  # no NOT NULL -> nullable
    assert cols["is_active"].default_value is not None
    assert "int" in cols["id"].type_str.lower()


def test_table_level_and_composite_primary_key(tmp_path: Path) -> None:
    entities, _ = _parse_sql(
        tmp_path,
        """
        CREATE TABLE membership (
            user_id INTEGER,
            group_id INTEGER,
            PRIMARY KEY (user_id, group_id)
        );
        """,
    )
    cols = {f.name: f for f in entities["membership"].fields}
    assert cols["user_id"].is_primary_key is True
    assert cols["group_id"].is_primary_key is True


def test_inline_and_alter_foreign_keys(tmp_path: Path) -> None:
    entities, _ = _parse_sql(
        tmp_path,
        """
        CREATE TABLE "user" (id INTEGER PRIMARY KEY);
        CREATE TABLE "order" (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES "user"(id)
        );
        CREATE TABLE invoice (id INTEGER PRIMARY KEY, order_id INTEGER);
        ALTER TABLE invoice ADD CONSTRAINT fk_o FOREIGN KEY (order_id) REFERENCES "order"(id);
        """,
    )
    order_cols = {f.name: f for f in entities["order"].fields}
    assert order_cols["user_id"].is_foreign_key is True
    assert order_cols["user_id"].foreign_table == "user.id"
    inv_cols = {f.name: f for f in entities["invoice"].fields}
    assert inv_cols["order_id"].is_foreign_key is True
    assert inv_cols["order_id"].foreign_table == "order.id"


def test_link_table_detected_structurally(tmp_path: Path) -> None:
    entities, _ = _parse_sql(
        tmp_path,
        """
        CREATE TABLE post (id INTEGER PRIMARY KEY);
        CREATE TABLE tag (id INTEGER PRIMARY KEY);
        CREATE TABLE post_tag (
            post_id INTEGER REFERENCES post(id),
            tag_id INTEGER REFERENCES tag(id),
            PRIMARY KEY (post_id, tag_id)
        );
        """,
    )
    assert entities["post_tag"].is_link_table is True


def test_ternary_link_table_detected_structurally(tmp_path: Path) -> None:
    """A composite PK of three FKs (no payload) is a link table too (#118)."""
    entities, _ = _parse_sql(
        tmp_path,
        """
        CREATE TABLE project (id INTEGER PRIMARY KEY);
        CREATE TABLE account (id INTEGER PRIMARY KEY);
        CREATE TABLE role (id INTEGER PRIMARY KEY);
        CREATE TABLE project_membership (
            project_id INTEGER REFERENCES project(id),
            account_id INTEGER REFERENCES account(id),
            role_id INTEGER REFERENCES role(id),
            PRIMARY KEY (project_id, account_id, role_id)
        );
        """,
    )
    assert entities["project_membership"].is_link_table is True


def test_composite_pk_with_payload_column_not_link_table(tmp_path: Path) -> None:
    """A composite PK of FKs plus a payload column is NOT a link table (#118)."""
    entities, _ = _parse_sql(
        tmp_path,
        """
        CREATE TABLE account (id INTEGER PRIMARY KEY);
        CREATE TABLE course (id INTEGER PRIMARY KEY);
        CREATE TABLE enrollment (
            account_id INTEGER REFERENCES account(id),
            course_id INTEGER REFERENCES course(id),
            grade VARCHAR(2),
            PRIMARY KEY (account_id, course_id)
        );
        """,
    )
    assert entities["enrollment"].is_link_table is False


def test_create_type_enum(tmp_path: Path) -> None:
    entities, enums = _parse_sql(
        tmp_path,
        """
        CREATE TYPE user_status AS ENUM ('active', 'banned');
        CREATE TABLE app_user (id INTEGER PRIMARY KEY, status user_status);
        """,
        dialect="postgres",
    )
    assert "user_status" in enums
    assert enums["user_status"].values == ["active", "banned"]


def test_exclude_pattern_drops_entity_and_relationship(tmp_path: Path) -> None:
    entities, _ = _parse_sql(
        tmp_path,
        """
        CREATE TABLE "user" (id INTEGER PRIMARY KEY);
        CREATE TABLE audit_log (id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES "user"(id));
        """,
        exclude_patterns=["audit_log"],
    )
    assert "audit_log" not in entities
    assert "user" in entities


def test_create_index_sets_index_flag(tmp_path: Path) -> None:
    entities, _ = _parse_sql(
        tmp_path,
        """
        CREATE TABLE app_user (id INTEGER PRIMARY KEY, email VARCHAR(255));
        CREATE INDEX ix_email ON app_user (email);
        """,
    )
    cols = {f.name: f for f in entities["app_user"].fields}
    assert cols["email"].index is True
    assert cols["id"].index is False


def test_composite_foreign_key_pairs_columns_positionally(tmp_path: Path) -> None:
    """Table-level FOREIGN KEY (a, b) REFERENCES parent(a, b) must pair columns positionally."""
    entities, _ = _parse_sql(
        tmp_path,
        """
        CREATE TABLE parent (a INTEGER, b INTEGER, PRIMARY KEY (a, b));
        CREATE TABLE child (
            a INTEGER,
            b INTEGER,
            FOREIGN KEY (a, b) REFERENCES parent(a, b)
        );
        """,
    )
    child_cols = {f.name: f for f in entities["child"].fields}
    assert child_cols["a"].is_foreign_key is True
    assert child_cols["a"].foreign_table == "parent.a"
    assert child_cols["b"].is_foreign_key is True
    assert child_cols["b"].foreign_table == "parent.b"


def test_composite_foreign_key_alter_table_pairs_columns_positionally(tmp_path: Path) -> None:
    """ALTER TABLE ... ADD FOREIGN KEY (a, b) REFERENCES parent(a, b) must pair positionally."""
    entities, _ = _parse_sql(
        tmp_path,
        """
        CREATE TABLE parent (a INTEGER, b INTEGER, PRIMARY KEY (a, b));
        CREATE TABLE child (a INTEGER, b INTEGER);
        ALTER TABLE child ADD CONSTRAINT fk FOREIGN KEY (a, b) REFERENCES parent(a, b);
        """,
    )
    child_cols = {f.name: f for f in entities["child"].fields}
    assert child_cols["a"].is_foreign_key is True
    assert child_cols["a"].foreign_table == "parent.a"
    assert child_cols["b"].is_foreign_key is True
    assert child_cols["b"].foreign_table == "parent.b"


def test_unresolvable_fk_reference_leaves_plain_column(tmp_path: Path) -> None:
    """A REFERENCES without a resolvable table must not flag the column as a foreign key.

    This guards the case where no exp.Table node can be found in the REFERENCES
    clause, which would otherwise produce a bogus foreign_table like ".id" in
    --format json output.
    """
    from sqlglot import exp

    f = tmp_path / "schema.sql"
    f.write_text("CREATE TABLE order_item (id INTEGER PRIMARY KEY, ghost_id INTEGER);")
    parser = SqlSchemaParser([f])
    entities, _ = parser.parse()  # same dict _set_fk mutates

    # Simulate the code path where ref_table comes back empty (unresolvable node).
    ghost = exp.to_identifier("ghost_id")
    parser._set_fks(entities["order_item"], [ghost], exp.Reference(this=exp.Schema()), exp)

    cols = {field.name: field for field in entities["order_item"].fields}
    assert cols["ghost_id"].is_foreign_key is False
    assert cols["ghost_id"].foreign_table is None


def test_schema_qualified_name_and_lenient_skipping(tmp_path: Path) -> None:
    entities, _ = _parse_sql(
        tmp_path,
        """
        CREATE SEQUENCE app_user_id_seq;
        CREATE TABLE public.app_user (id INTEGER PRIMARY KEY);
        INSERT INTO public.app_user (id) VALUES (1);
        GRANT SELECT ON public.app_user TO readonly;
        """,
    )
    assert "app_user" in entities  # schema prefix stripped, noise ignored


def test_unique_single_column_fk_marked(tmp_path: Path) -> None:
    entities, _ = _parse_sql(
        tmp_path,
        """
        CREATE TABLE customer (id INTEGER PRIMARY KEY);
        CREATE TABLE profile (
            id INTEGER PRIMARY KEY,
            customer_id INTEGER NOT NULL UNIQUE REFERENCES customer(id),
            handle VARCHAR(50),
            a INTEGER,
            b INTEGER,
            email VARCHAR(100),
            c INTEGER,
            d INTEGER,
            UNIQUE (handle),
            UNIQUE (a, b),
            CONSTRAINT uq_email UNIQUE (email),
            CONSTRAINT uq_cd UNIQUE (c, d)
        );
        """,
    )
    cols = {f.name: f for f in entities["profile"].fields}
    assert cols["customer_id"].is_unique is True  # inline UNIQUE
    assert cols["customer_id"].is_foreign_key is True
    assert cols["handle"].is_unique is True  # single-col table-level UNIQUE
    assert cols["a"].is_unique is False  # composite UNIQUE ignored
    assert cols["b"].is_unique is False
    assert cols["id"].is_unique is False  # PK not marked unique
    assert cols["email"].is_unique is True  # named single-col table-level UNIQUE
    assert cols["c"].is_unique is False  # named composite UNIQUE ignored
    assert cols["d"].is_unique is False


def test_primary_key_with_explicit_unique_not_marked_unique(tmp_path: Path) -> None:
    # A PK is inherently unique, but is_unique is reserved for a non-PK
    # uniqueness that implies 1:1. An explicit UNIQUE on a PK column (inline or
    # table-level) must not leak is_unique=True into the IR/JSON.
    entities, _ = _parse_sql(
        tmp_path,
        """
        CREATE TABLE inline_pk (id INTEGER PRIMARY KEY UNIQUE);
        CREATE TABLE table_pk (
            id INTEGER PRIMARY KEY,
            UNIQUE (id)
        );
        """,
    )
    assert entities["inline_pk"].fields[0].is_primary_key is True
    assert entities["inline_pk"].fields[0].is_unique is False
    assert entities["table_pk"].fields[0].is_primary_key is True
    assert entities["table_pk"].fields[0].is_unique is False


def test_missing_sqlglot_raises_helpful_error(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    f = tmp_path / "schema.sql"
    f.write_text("CREATE TABLE a (id INT);")
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == "sqlglot":
            raise ImportError("no sqlglot")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(SqlDependencyError, match=r"pip install erdify\[sql\]"):
        SqlSchemaParser([f]).parse()


# ---------------------------------------------------------------------------
# Task 8: orchestration tests
# ---------------------------------------------------------------------------
from erdify.parser import parse_models_directory  # noqa: E402


def test_parse_models_directory_picks_up_sql(tmp_path: Path) -> None:
    (tmp_path / "schema.sql").write_text('CREATE TABLE "user" (id INTEGER PRIMARY KEY);')
    entities, _ = parse_models_directory(tmp_path, include_patterns=["*.sql"])
    assert "user" in entities


def test_parse_models_directory_accepts_a_file(tmp_path: Path) -> None:
    f = tmp_path / "schema.sql"
    f.write_text("CREATE TABLE thing (id INTEGER PRIMARY KEY);")
    entities, _ = parse_models_directory(f)
    assert "thing" in entities


def test_public_export() -> None:
    import erdify

    assert hasattr(erdify, "SqlSchemaParser")


def test_import_erdify_does_not_import_sqlglot():
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import erdify, sys; assert 'sqlglot' not in sys.modules, 'sqlglot imported eagerly'",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# Task 10: golden integration fixture + Python↔SQL parity test
# ---------------------------------------------------------------------------
from erdify.generator import generate_mermaid, generate_plantuml  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "sql"


def test_sql_golden_matches() -> None:
    entities, enums = parse_models_directory(FIX / "ecommerce.sql", sql_dialect="postgres")
    rendered = generate_plantuml(entities=entities, enums=enums, title="E-Commerce ERD")
    expected = (FIX / "expected.puml").read_text().rstrip("\n")
    assert rendered == expected


def test_sql_and_python_render_equivalent_structure(tmp_path: Path) -> None:
    # Minimal user/order schema in SQL...
    (tmp_path / "schema.sql").write_text(
        'CREATE TABLE "user" (id INTEGER PRIMARY KEY, email VARCHAR NOT NULL);'
        'CREATE TABLE "order" (id INTEGER PRIMARY KEY, '
        'user_id INTEGER NOT NULL REFERENCES "user"(id));'
    )
    sql_entities, _ = parse_models_directory(tmp_path / "schema.sql")
    # ...and the same in SQLModel.
    (tmp_path / "models.py").write_text(
        "from sqlmodel import SQLModel, Field\n"
        "class User(SQLModel, table=True):\n"
        "    id: int = Field(primary_key=True)\n"
        "    email: str\n"
        "class Order(SQLModel, table=True):\n"
        "    id: int = Field(primary_key=True)\n"
        '    user_id: int = Field(foreign_key="user.id")\n'
    )
    py_entities, _ = parse_models_directory(tmp_path, include_patterns=["models.py"])

    def fk_pairs(entities):  # type: ignore[no-untyped-def]
        return {
            (e.table_name, f.foreign_table.split(".")[0])
            for e in entities.values()
            for f in e.fields
            if f.is_foreign_key and f.foreign_table
        }

    assert fk_pairs(sql_entities) == fk_pairs(py_entities) == {("order", "user")}


def test_table_level_primary_key_is_not_nullable(tmp_path: Path) -> None:
    """A table-level PRIMARY KEY (...) also implies NOT NULL (#217)."""
    entities, _ = _parse_sql(
        tmp_path,
        """
        CREATE TABLE a (x INTEGER, y INTEGER, PRIMARY KEY (x, y));
        """,
    )
    assert not any(f.is_nullable for f in entities["a"].fields)


def test_pk_that_is_also_fk_keeps_mandatory_parent(tmp_path: Path) -> None:
    """A PK column is NOT NULL, so its FK edge must not turn optional (#216/#217)."""
    entities, _ = _parse_sql(
        tmp_path,
        """
        CREATE TABLE "order" (id INTEGER PRIMARY KEY);
        CREATE TABLE order_line (
            order_id INTEGER REFERENCES "order"(id),
            line_no INTEGER,
            note TEXT,
            PRIMARY KEY (order_id, line_no)
        );
        """,
    )
    out = generate_mermaid(entities)
    assert "order_line }o--|| order" in out


# ---------------------------------------------------------------------------
# Findings of the SQL ground-truth tests (#266)
# ---------------------------------------------------------------------------


def _cols(entities, table):  # type: ignore[no-untyped-def]
    return {f.name: f for f in entities[table].fields}


def test_explicit_null_constraint_is_nullable(tmp_path: Path) -> None:
    entities, _ = _parse_sql(
        tmp_path,
        """
        CREATE TABLE parent (id INTEGER PRIMARY KEY);
        CREATE TABLE child (
            id INTEGER PRIMARY KEY,
            label TEXT NULL,
            parent_id INTEGER NULL REFERENCES parent(id),
            code TEXT NOT NULL
        );
        """,
    )
    cols = _cols(entities, "child")
    assert cols["label"].is_nullable is True
    assert cols["parent_id"].is_nullable is True
    assert cols["code"].is_nullable is False
    assert "child }o--o| parent" in generate_mermaid(entities)


def test_reference_without_columns_targets_the_primary_key(tmp_path: Path) -> None:
    entities, _ = _parse_sql(
        tmp_path,
        """
        CREATE TABLE city (
            id INTEGER PRIMARY KEY,
            country_code CHAR(2) REFERENCES country,
            edition_book INTEGER,
            edition_no INTEGER,
            FOREIGN KEY (edition_book, edition_no) REFERENCES edition
        );
        CREATE TABLE country (code CHAR(2) PRIMARY KEY);
        CREATE TABLE edition (book INTEGER, no INTEGER, PRIMARY KEY (book, no));
        """,
    )
    cols = _cols(entities, "city")
    assert cols["country_code"].foreign_table == "country.code"  # defined further down
    assert cols["edition_book"].foreign_table == "edition.book"  # in key order
    assert cols["edition_no"].foreign_table == "edition.no"


def test_reference_to_an_unknown_table_without_columns_keeps_id(tmp_path: Path) -> None:
    entities, _ = _parse_sql(
        tmp_path, "CREATE TABLE a (id INTEGER PRIMARY KEY, x_id INTEGER REFERENCES elsewhere);"
    )
    assert _cols(entities, "a")["x_id"].foreign_table == "elsewhere.id"


def test_names_are_matched_case_insensitively(tmp_path: Path) -> None:
    entities, _ = _parse_sql(
        tmp_path,
        """
        CREATE TABLE customer (id INTEGER PRIMARY KEY);
        CREATE TABLE invoice (
            id INTEGER,
            customer_id INTEGER NOT NULL REFERENCES Customer(ID),
            payer_id INTEGER,
            email TEXT,
            FOREIGN KEY (PAYER_ID) REFERENCES CUSTOMER (Id),
            PRIMARY KEY (ID),
            UNIQUE (Email)
        );
        CREATE UNIQUE INDEX ux ON INVOICE (EMAIL);
        """,
    )
    cols = _cols(entities, "invoice")
    assert cols["customer_id"].foreign_table == "customer.id"
    assert cols["payer_id"].foreign_table == "customer.id"
    assert cols["id"].is_primary_key is True
    assert cols["email"].is_unique is True
    assert cols["email"].index is True


def test_quoted_names_keep_their_case_in_postgres(tmp_path: Path) -> None:
    """PostgreSQL folds unquoted names to lower case and keeps quoted ones as written."""
    entities, _ = _parse_sql(
        tmp_path,
        """
        CREATE TABLE "Account" (id INTEGER PRIMARY KEY);
        CREATE TABLE account (id INTEGER PRIMARY KEY);
        CREATE TABLE ledger (
            id INTEGER PRIMARY KEY,
            a_id INTEGER REFERENCES "Account"(id),
            b_id INTEGER REFERENCES account(id),
            c_id INTEGER REFERENCES ACCOUNT(id),
            d_id INTEGER REFERENCES Account(ID)
        );
        """,
        dialect="postgres",
    )
    cols = _cols(entities, "ledger")
    assert cols["a_id"].foreign_table == "Account.id"
    assert cols["b_id"].foreign_table == "account.id"
    assert cols["c_id"].foreign_table == "account.id"
    assert cols["d_id"].foreign_table == "account.id"


def test_unique_index_on_one_column_makes_it_unique(tmp_path: Path) -> None:
    entities, _ = _parse_sql(
        tmp_path,
        """
        CREATE TABLE customer (id INTEGER PRIMARY KEY);
        CREATE TABLE card (
            id INTEGER PRIMARY KEY,
            customer_id INTEGER NOT NULL REFERENCES customer(id),
            first_name TEXT,
            last_name TEXT,
            referral TEXT,
            nickname TEXT
        );
        CREATE UNIQUE INDEX ux_customer ON card (customer_id);
        CREATE UNIQUE INDEX ux_id ON card (id);
        CREATE UNIQUE INDEX ux_name ON card (first_name, last_name);
        CREATE UNIQUE INDEX ux_referral ON card (referral) WHERE referral IS NOT NULL;
        CREATE UNIQUE INDEX ux_nickname ON card (lower(nickname));
        """,
    )
    cols = _cols(entities, "card")
    assert cols["customer_id"].is_unique is True
    assert cols["id"].is_unique is False  # a primary key is never marked
    assert not any(cols[c].is_unique for c in ("first_name", "last_name", "referral", "nickname"))
    assert "card |o--|| customer" in generate_mermaid(entities)


def test_expression_index_sets_no_index_flag(tmp_path: Path) -> None:
    """docs/frameworks/sql.md: only plain-column indexes set the JSON index flag."""
    entities, _ = _parse_sql(
        tmp_path,
        """
        CREATE TABLE person (id INTEGER PRIMARY KEY, email TEXT, name TEXT);
        CREATE INDEX ix_email ON person (lower(email));
        CREATE INDEX ix_name ON person (name DESC);
        """,
    )
    cols = _cols(entities, "person")
    assert cols["email"].index is False
    assert cols["name"].index is True


def test_a_statement_that_fails_to_parse_keeps_the_rest_of_the_file(tmp_path: Path) -> None:
    sql = (
        "CREATE TABLE plain (id INTEGER PRIMARY KEY);\n"
        "CREATE TABLE box (id INTEGER PRIMARY KEY,"
        " area INTEGER GENERATED ALWAYS AS (id * 2) STORED);\n"
        "CREATE TABLE after (id INTEGER PRIMARY KEY, plain_id INTEGER REFERENCES plain(id));\n"
    )
    entities, _ = _parse_sql(tmp_path, sql)
    assert set(entities) == {"plain", "after"}  # box needs --sql-dialect (limitation)
    with pytest.raises(ModelParseError):
        _parse_sql(tmp_path, sql, strict=True)


def test_table_options_sqlglot_does_not_know_are_ignored(tmp_path: Path) -> None:
    """SQLite's WITHOUT ROWID makes sqlglot fall back to a Command; the table is kept."""
    entities, _ = _parse_sql(
        tmp_path,
        """
        CREATE TABLE kv (key TEXT PRIMARY KEY, value BLOB) WITHOUT ROWID;
        CREATE TABLE reading (id INTEGER PRIMARY KEY, kv_key TEXT NOT NULL REFERENCES kv(key));
        """,
        dialect="sqlite",
    )
    assert _cols(entities, "kv")["key"].is_primary_key is True
    assert _cols(entities, "reading")["kv_key"].foreign_table == "kv.key"


def test_unreadable_create_table_is_reported(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    entities, _ = _parse_sql(tmp_path, "CREATE TABLE odd WITHOUT ROWID;\nCREATE TABLE ok (id INT);")
    assert set(entities) == {"ok"}
    assert "Unsupported" in capsys.readouterr().err


def test_collated_and_opclass_index_columns_are_columns(tmp_path: Path) -> None:
    entities, _ = _parse_sql(
        tmp_path,
        """
        CREATE TABLE member (id INTEGER PRIMARY KEY, email TEXT, handle TEXT);
        CREATE UNIQUE INDEX ux_email ON member (email COLLATE NOCASE);
        CREATE INDEX ix_handle ON member (handle varchar_pattern_ops);
        """,
        dialect="postgres",
    )
    cols = _cols(entities, "member")
    assert cols["email"].is_unique is True
    assert cols["email"].index is True
    assert cols["handle"].index is True


def test_other_create_commands_are_skipped_silently(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    """A CREATE ... TABLE sqlglot can't parse that isn't a plain table stays a skip."""
    sql = "CREATE VIRTUAL TABLE fts USING fts5(a, b);\nCREATE TABLE ok (id INT);"
    entities, _ = _parse_sql(tmp_path, sql, strict=True)
    assert set(entities) == {"ok"}
    assert "Error parsing" not in capsys.readouterr().err


def test_strict_error_names_each_file_once(tmp_path: Path) -> None:
    with pytest.raises(ModelParseError, match=r"^1 file\(s\) could not be parsed") as raised:
        _parse_sql(tmp_path, "CREATE TABLE (;\nCREATE TABLE (;\n", strict=True)
    assert len(raised.value.errors) == 2  # one per statement


def test_recovered_table_logs_no_fallback_warning(tmp_path: Path, caplog) -> None:  # type: ignore[no-untyped-def]
    """sqlglot's "Falling back to parsing as a 'Command'" is kept only for what is skipped."""
    _parse_sql(tmp_path, "CREATE TABLE kv (k TEXT PRIMARY KEY) WITHOUT ROWID;", dialect="sqlite")
    assert "Falling back" not in caplog.text
    _parse_sql(tmp_path, "CREATE VIRTUAL TABLE fts USING fts5(a);")
    assert "Falling back" in caplog.text


def test_column_in_two_foreign_keys_keeps_the_first(tmp_path: Path) -> None:
    entities, _ = _parse_sql(
        tmp_path,
        """
        CREATE TABLE a (id INTEGER PRIMARY KEY);
        CREATE TABLE b (id INTEGER PRIMARY KEY);
        CREATE TABLE c (
            id INTEGER PRIMARY KEY,
            x INTEGER REFERENCES a(id),
            FOREIGN KEY (x) REFERENCES b(id)
        );
        """,
    )
    assert _cols(entities, "c")["x"].foreign_table == "a.id"


def test_column_typed_with_a_quoted_enum_name_matches_the_enum(tmp_path: Path) -> None:
    """A quoted type name loses its quotes and keeps its case, like the
    ``CREATE TYPE`` name it refers to (#328)."""
    entities, enums = _parse_sql(
        tmp_path,
        """
        CREATE TYPE "order state" AS ENUM ('new', 'done');
        CREATE TYPE "Tone" AS ENUM ('calm');
        CREATE TABLE t (id INTEGER PRIMARY KEY, s "order state", n "Tone");
        """,
        dialect="postgres",
    )
    types = {f.name: f.type_str for f in entities["t"].fields}
    assert types == {"id": "int", "s": "order state", "n": "Tone"}
    assert set(enums) == {"order state", "Tone"}


def test_column_type_resolves_to_the_enum_as_the_dialect_folds_names(tmp_path: Path) -> None:
    """Unquoted type names are case-insensitive: ``mood`` is the enum ``Mood``,
    even when the type is created after the table (#328)."""
    entities, _ = _parse_sql(
        tmp_path,
        """
        CREATE TABLE t (id INTEGER PRIMARY KEY, m mood, d MyDomain, x "MyDomain");
        CREATE TYPE Mood AS ENUM ('happy', 'sad');
        """,
        dialect="postgres",
    )
    types = {f.name: f.type_str for f in entities["t"].fields}
    assert types == {"id": "int", "m": "Mood", "d": "mydomain", "x": "MyDomain"}


def test_schema_qualified_column_type_keeps_its_schema(tmp_path: Path) -> None:
    """A schema-qualified enum type resolves to the enum, schema kept (#328)."""
    entities, _ = _parse_sql(
        tmp_path,
        """
        CREATE TYPE public."order state" AS ENUM ('new', 'done');
        CREATE TABLE t (
            id INTEGER PRIMARY KEY, s public."order state", q "MySchema"."order state"
        );
        """,
        dialect="postgres",
    )
    types = [f.type_str for f in entities["t"].fields[1:]]
    assert types == ["public.order state", "MySchema.order state"]


def test_quoted_enum_type_is_drawn(tmp_path: Path) -> None:
    """The enum a quoted column type names is drawn in PlantUML and Mermaid (#328)."""
    entities, enums = _parse_sql(
        tmp_path,
        """
        CREATE TYPE "order state" AS ENUM ('new', 'done');
        CREATE TABLE t (id INTEGER PRIMARY KEY, s "order state");
        """,
        dialect="postgres",
    )
    assert 'enum "order state" as order_state' in generate_plantuml(entities, enums)
    assert '"order state" {' in generate_mermaid(entities, enums)
