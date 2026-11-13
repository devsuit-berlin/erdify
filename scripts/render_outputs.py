"""Write erdify's output in every format for every test fixture and docs example.

The renderer check (``.github/workflows/test.yml``, job ``renderers``) feeds
the files to the real renderers: PlantUML (``-checkonly``), Mermaid in
headless Chromium (``scripts/renderers/check.mjs``), which also loads each
HTML page. ``tests/test_json_schema.py`` validates the JSON with the
published schema through :func:`sources`.

Sources: every fixture directory under ``tests/fixtures/`` (one diagram per
directory), every module of the edge-case catalogs (one diagram per module),
and every directory under ``docs/examples/``. SQL sources are parsed with the
dialect the SQL ground-truth tests use for them.

Usage::

    uv run python scripts/render_outputs.py OUT_DIR

Writes ``OUT_DIR/<id>.puml``, ``.mmd``, ``.html`` and ``.json`` per source,
where ``<id>`` is the source's path with ``/`` replaced by ``__``.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from erdify import (
    generate_html,
    generate_json,
    generate_mermaid,
    generate_plantuml,
    parse_models_directory,
)

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
EXAMPLES = ROOT / "docs" / "examples"
# Sources with nothing to draw (deliberately empty or unparsable input): a
# fixture directory by name, a catalog module as "<catalog>/<stem>".
NO_DIAGRAM = {"empty", "malformed"}
# Dialects of the SQL sources (the SQL ground-truth tests' DIALECTS, by file
# stem or fixture path); the rest is parsed without one.
SQL_DIALECTS = {
    "fixtures/sql": "postgres",
    "postgres_dialect": "postgres",
    "quoted_enum_type": "postgres",
    "sqlite_table_options": "sqlite",
    "generated_column": "sqlite",
}
# Sources that only draw with --base-classes (bases defined outside the scan).
BASE_CLASSES = {"fixtures/base_classes": ["Schema"]}


@dataclass(frozen=True)
class Source:
    """One diagram: a fixture directory, a catalog module or a docs example."""

    id: str
    path: Path
    include_patterns: list[str] | None = None
    sql_dialect: str | None = None
    base_classes: list[str] | None = None


def sources() -> Iterator[Source]:
    """Every source, in a stable order."""
    for directory in sorted(p for p in FIXTURES.iterdir() if p.is_dir()):
        name = directory.name
        if name in NO_DIAGRAM or name.startswith("__"):
            continue
        if name.endswith("_edge_cases"):
            for module in sorted(directory.glob("*.py")) + sorted(directory.glob("*.sql")):
                if module.name == "__init__.py" or f"{name}/{module.stem}" in NO_DIAGRAM:
                    continue
                is_sql = module.suffix == ".sql"
                yield Source(
                    id=f"fixtures/{name}/{module.stem}",
                    path=module if is_sql else directory,
                    include_patterns=None if is_sql else [module.name],
                    # The dialect keys are SQL file stems: Python modules get none.
                    sql_dialect=SQL_DIALECTS.get(module.stem) if is_sql else None,
                )
        else:
            key = f"fixtures/{name}"
            include = ["**/*.sql"] if any(directory.glob("*.sql")) else None
            yield Source(key, directory, include, SQL_DIALECTS.get(key), BASE_CLASSES.get(key))
    for directory in sorted(p for p in EXAMPLES.iterdir() if p.is_dir()):
        yield Source(f"docs/examples/{directory.name}", directory)


def render(source: Source) -> dict[str, str]:
    """The source's diagram in every format, by file extension."""
    entities, enums = parse_models_directory(
        source.path,
        include_patterns=source.include_patterns,
        sql_dialect=source.sql_dialect,
        base_classes=source.base_classes,
        # A fixture under site-packages is skipped by default; draw it anyway.
        use_default_excludes=False,
    )
    if not entities:
        raise ValueError(f"{source.id}: nothing to draw")
    title = source.id
    return {
        "puml": generate_plantuml(entities, enums, title=title),
        "mmd": generate_mermaid(entities, enums, title=title),
        "html": generate_html(entities, enums, title=title),
        "json": generate_json(entities, enums, title=title),
    }


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    out = Path(argv[0])
    out.mkdir(parents=True, exist_ok=True)
    count, errors = 0, []
    for source in sources():
        try:
            outputs = render(source)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        stem = source.id.replace("/", "__")
        for extension, text in outputs.items():
            (out / f"{stem}.{extension}").write_text(text, encoding="utf-8")
        count += 1
    print(f"Wrote {count} diagrams in 4 formats to {out}")
    for error in errors:
        print(f"error: {error}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
