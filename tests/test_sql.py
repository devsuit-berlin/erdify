from pathlib import Path

from erdify.sql_parser import SqlSchemaParser, discover_sql_files


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
