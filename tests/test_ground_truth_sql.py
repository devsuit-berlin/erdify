"""Ground truth: erdify's SQL DDL parse must match what SQLite builds (#266).

Every SQL DDL source the suite uses (the SQL fixture, the docs example, the
edge-case catalog in ``fixtures/sql_edge_cases`` and the inline DDL of the
regression tests) is parsed by erdify and executed in an in-memory SQLite
database (stdlib ``sqlite3``). Both are reduced to the same normalised schema
(tables, columns, primary / unique / foreign keys, nullability) and must agree.
Enums are not compared: SQLite has no enum types.

Running the DDL is SQLite's validation of the test data, and its foreign-key
check (a parent table that exists, a parent key that is a primary key or
unique) has to pass too, unless ``EXPECTED_CHECK_ERRORS`` lists the source.

Nothing is skipped silently: known differences, documented limitations and
sources SQLite can't run are each listed below with a reason. A strict
``xfail`` turns into a failure once its issue is fixed, an unlisted rejection
fails, and a listed name that no longer exists fails.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import sqlglot
from packaging.version import Version

from tests.ground_truth import sqlite_ref
from tests.ground_truth.schema import Schema, from_erdify
from tests.ground_truth.snippets import Snippet, sql_snippets

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"


def _docs_sql(page: str) -> str:
    """The ``sql`` code blocks of a docs page, joined."""
    text = (ROOT / page).read_text(encoding="utf-8")
    return "\n".join(re.findall(r"```sql\n(.*?)```", text, flags=re.DOTALL))


MODULES = {
    "fixtures/sql": (FIXTURES / "sql" / "ecommerce.sql").read_text(encoding="utf-8"),
    "docs/frameworks/sql.md": _docs_sql("docs/frameworks/sql.md"),
}

EDGE_CASES_DIR = FIXTURES / "sql_edge_cases"
EDGE_CASES = sorted(EDGE_CASES_DIR.glob("*.sql"))

SNIPPETS = sql_snippets()

# The sqlglot dialect a source is written in, for erdify (--sql-dialect) and
# for the statements SQLite only runs once transpiled. Unlisted: generic.
DIALECTS = {
    "fixtures/sql": "postgres",
    "docs/frameworks/sql.md": "postgres",
    "postgres_dialect": "postgres",
    "sqlite_table_options": "sqlite",
    "generated_column": "sqlite",
    "test_sql.py::test_create_type_enum": "postgres",
    "test_ground_truth_sql.py::test_reference_transpiles_only_the_statements_sqlite_rejects"
    ".schema": "postgres",
}

# erdify output that differs from SQLite's schema, pending a fix.
KNOWN_DIFFERENCES: dict[str, str] = {}

# Documented in docs/frameworks/sql.md; strict xfails, so that the page is
# updated once one is supported.
GENERATED_GENERIC = "sql.md: a generated column with STORED / VIRTUAL needs --sql-dialect"
LIMITATIONS = {
    "generated_column_generic": GENERATED_GENERIC,
    "test_sql.py::test_a_statement_that_fails_to_parse_keeps_the_rest_of_the_file.sql": (
        GENERATED_GENERIC
    ),
    "test_sql.py::test_other_create_commands_are_skipped_silently.sql": (
        "sql.md: virtual tables (CREATE VIRTUAL TABLE) are not drawn"
    ),
}

# The oldest supported sqlglot is 30.8 (docs/installation.md); CI runs these
# tests on it and on the locked release. erdify follows the newest sqlglot;
# where an older release can't parse a source, it differs before that release:
# name -> (release, reason).
SQLGLOT_VERSION = Version(sqlglot.__version__).release[:3]
SQLGLOT_DIFFERENCES = {
    "generated_column": (
        (30, 17),
        "sqlglot before 30.17 can't parse SQLite's short form `col TEXT AS (expr)`",
    ),
}

# Inline snippets whose foreign keys SQLite's check rejects on purpose: the
# reported "<table>: <error>" entries and why. Every other source must pass,
# and the fixture, the docs example and the catalog always must.
EXPECTED_CHECK_ERRORS = {
    "test_ground_truth_sql.py::test_reference_reports_foreign_key_errors.schema": (
        ("b: foreign key mismatch", "c: no such table"),
        "the harness's own test that foreign-key errors are reported",
    ),
}

# Sources SQLite can't run, each a deliberate test of erdify on DDL that isn't
# (only) SQLite's.
NO_ALTER_CONSTRAINT = "SQLite has no ALTER TABLE ... ADD CONSTRAINT"
EXPECTED_REJECTED = {
    "test_sql.py::test_inline_and_alter_foreign_keys": NO_ALTER_CONSTRAINT,
    "test_sql.py::test_composite_foreign_key_alter_table_pairs_columns_positionally": (
        NO_ALTER_CONSTRAINT
    ),
    "test_sql.py::test_schema_qualified_name_and_lenient_skipping": (
        "a schema-qualified table among CREATE SEQUENCE / INSERT / GRANT noise erdify must skip"
    ),
    "test_strict.py::mixed_tree": "a syntax error, for --strict",
    "test_sql.py::test_strict_error_names_each_file_once": "syntax errors, for --strict",
    "test_sql.py::test_reference_to_an_unknown_table_without_columns_keeps_id": (
        "a bare REFERENCES to a table the source doesn't define; erdify falls back to id"
    ),
    "test_sql.py::test_quoted_names_keep_their_case_in_postgres": (
        'PostgreSQL keeps quoted "Account" and account apart; SQLite folds them'
    ),
    "test_sql.py::test_collated_and_opclass_index_columns_are_columns": (
        "a PostgreSQL operator class (varchar_pattern_ops)"
    ),
    "test_sql.py::test_unreadable_create_table_is_reported": (
        "a table without a column list, for the parse error"
    ),
    "test_ground_truth_sql.py::test_reference_rejects_ddl_sqlite_cannot_run": (
        "the harness's own test of DDL SQLite can't run"
    ),
}


def _param(name: str, value: object) -> object:
    reason = KNOWN_DIFFERENCES.get(name) or LIMITATIONS.get(name)
    until, sqlglot_reason = SQLGLOT_DIFFERENCES.get(name, ((), ""))
    if not reason and until and SQLGLOT_VERSION < until:
        reason = sqlglot_reason
    marks = [pytest.mark.xfail(reason=reason, raises=AssertionError, strict=True)] if reason else []
    return pytest.param(value, id=name, marks=marks)


def _erdify(name: str, source: str, tmp_path: Path) -> Schema:
    path = tmp_path / "schema.sql"
    path.write_text(source, encoding="utf-8")
    return from_erdify(path, "sql", sql_dialect=DIALECTS.get(name))


def _check(name: str, source: str, tmp_path: Path, *, strict: bool = False) -> None:
    """Compare erdify with SQLite for one source.

    ``strict`` sources (the fixture, the docs example, the catalog) must run
    and pass the foreign-key check; the lists only apply to inline snippets.
    """
    try:
        expected = sqlite_ref.load(source, dialect=DIALECTS.get(name))
    except sqlite_ref.Unloadable as exc:
        if name in EXPECTED_REJECTED and not strict:
            pytest.skip(f"SQLite can't run this source ({EXPECTED_REJECTED[name]}): {exc}")
        pytest.fail(
            f"SQLite can't run {name}: {exc}. Fix the source, or list it in "
            "EXPECTED_REJECTED if it is a deliberate test of other DDL."
        )
    allowed, reason = ((), "") if strict else EXPECTED_CHECK_ERRORS.get(name, ((), ""))
    if expected.checks != allowed:
        # pytest.fail, not assert: a known-difference xfail only accepts an
        # AssertionError, so invalid test data must not hide behind one.
        pytest.fail(
            f"SQLite's foreign-key check of {name} reports {list(expected.checks) or 'nothing'}, "
            f"expected {list(allowed) or 'nothing'}"
            + (f" (listed: {reason})" if reason else "")
            + ". Fix the source, or list a deliberate error in EXPECTED_CHECK_ERRORS."
        )
    assert _erdify(name, source, tmp_path).tables == expected.tables


@pytest.mark.parametrize("name", [_param(n, n) for n in sorted(MODULES)])
def test_module_matches_sqlite(name: str, tmp_path: Path) -> None:
    _check(name, MODULES[name], tmp_path, strict=True)


@pytest.mark.parametrize("path", [_param(p.stem, p) for p in EDGE_CASES])
def test_edge_case_matches_sqlite(path: Path, tmp_path: Path) -> None:
    _check(path.stem, path.read_text(encoding="utf-8"), tmp_path, strict=True)


@pytest.mark.parametrize("snippet", [_param(s.id, s) for s in SNIPPETS])
def test_snippet_matches_sqlite(snippet: Snippet, tmp_path: Path) -> None:
    _check(snippet.id, snippet.source, tmp_path)


def test_known_lists_name_existing_sources() -> None:
    """A renamed or deleted test must not leave a stale entry behind."""
    names = {s.id for s in SNIPPETS} | {p.stem for p in EDGE_CASES} | set(MODULES)
    listed = (
        set(KNOWN_DIFFERENCES)
        | set(LIMITATIONS)
        | set(SQLGLOT_DIFFERENCES)
        | set(EXPECTED_CHECK_ERRORS)
        | set(EXPECTED_REJECTED)
        | set(DIALECTS)
    )
    assert not listed - names


def test_most_sources_are_compared() -> None:
    """Guard the discovery and the lists: most sources must really be compared."""
    compared = [s for s in SNIPPETS if s.id not in EXPECTED_REJECTED]
    assert len(compared) >= 20
    assert len(EDGE_CASES) >= 20
    assert all(MODULES.values())  # the docs page still has its sql block


# --- the reference loader itself -------------------------------------------


def test_reference_reads_keys_nullability_and_uniqueness() -> None:
    schema = sqlite_ref.load(
        "CREATE TABLE country (code TEXT PRIMARY KEY);\n"
        "CREATE TABLE city (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE,\n"
        "    country_code TEXT REFERENCES Country);\n"
    )
    city = schema.tables["city"].columns
    assert schema.tables["country"].columns["code"].nullable is False  # the PK quirk
    assert city["name"].unique and not city["name"].nullable
    assert city["country_code"].fk == "country.code"  # bare REFERENCES -> the parent PK
    assert schema.checks == ()


def test_reference_reports_foreign_key_errors() -> None:
    schema = sqlite_ref.load(
        "CREATE TABLE a (id INTEGER PRIMARY KEY, name TEXT);\n"
        "CREATE TABLE b (id INTEGER PRIMARY KEY, a_name TEXT REFERENCES a(name));\n"
        "CREATE TABLE c (id INTEGER PRIMARY KEY, ghost_id INTEGER REFERENCES ghost(id));\n"
    )
    assert schema.checks == ("b: foreign key mismatch", "c: no such table")
    assert schema.tables["c"].columns["ghost_id"].fk == "ghost.id"


def test_reference_rejects_ddl_sqlite_cannot_run() -> None:
    with pytest.raises(sqlite_ref.Unloadable, match="syntax error"):
        sqlite_ref.load("CREATE TABLE a (id INT);\nALTER TABLE a ADD CONSTRAINT x UNIQUE (id);\n")


def test_reference_transpiles_only_the_statements_sqlite_rejects() -> None:
    """``DEFAULT NOW()`` needs transpiling, a CREATE TYPE is dropped, the index runs as written."""
    schema = sqlite_ref.load(
        "CREATE TYPE mood AS ENUM ('ok');\n"
        "CREATE TABLE t (id SERIAL PRIMARY KEY, at TIMESTAMP NOT NULL DEFAULT NOW(), m mood);\n"
        "CREATE INDEX ix_at ON t (at);\n",
        dialect="postgres",
    )
    assert set(schema.tables["t"].columns) == {"id", "at", "m"}


def test_statements_split_like_sqlite() -> None:
    """A ``;`` inside a literal or comment doesn't end a statement."""
    statements = sqlite_ref._statements(
        "CREATE TABLE a (x TEXT DEFAULT ';');\n-- a; comment\nCREATE TABLE b (y INT)"
    )
    assert len(statements) == 2
