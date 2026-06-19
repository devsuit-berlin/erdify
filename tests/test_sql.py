from pathlib import Path

from erdify.sql_parser import discover_sql_files


def test_discover_sql_files_matches_include_and_skips_py(tmp_path: Path):
    (tmp_path / "schema.sql").write_text("CREATE TABLE a (id INT);")
    (tmp_path / "models.py").write_text("x = 1")
    sub = tmp_path / ".venv" / "pkg"
    sub.mkdir(parents=True)
    (sub / "vendor.sql").write_text("CREATE TABLE b (id INT);")

    found = discover_sql_files(tmp_path, ["*.sql"], [], use_default_excludes=True)

    assert [p.name for p in found] == ["schema.sql"]  # .py ignored, .venv pruned
