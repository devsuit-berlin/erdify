import builtins
from pathlib import Path

import pytest

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
from erdify.generator import generate_plantuml  # noqa: E402

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
