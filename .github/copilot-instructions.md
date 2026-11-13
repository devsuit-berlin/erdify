# Copilot / AI agent instructions

This is the single source of truth for AI-agent and contributor guidance in this
repository. `CLAUDE.md` and `AGENTS.md` point here.

## Language policy

**The entire project scope is English-only.** This applies to code, comments,
docstrings, documentation, commit messages, PR titles and descriptions, release
notes, changelog entries, announcements, and issues. No exceptions, regardless
of the language a request is written in.

## Commands

This project uses [uv](https://docs.astral.sh/uv/). Apart from `uv sync`, the commands below run through `uv run`.

```bash
uv sync                                  # Install deps into .venv (use --frozen in CI)

uv run pytest                            # Run the full test suite
uv run pytest tests/test_parser.py       # A single file
uv run pytest tests/test_parser.py::test_name   # A single test
uv run pytest -k "foreign_key"           # Tests matching an expression
uv run pytest --cov=erdify --cov-report=term-missing   # With coverage (gate: 90%)

uv run mypy src/                         # Type check (strict mode, must pass)
uv run ruff check src/ tests/            # Lint
uv run ruff format src/ tests/           # Format

uv run python scripts/gen_cli_docs.py    # Regenerate docs/usage/cli.md from the argparse parser
```

`pre-commit` runs ruff + mypy + the CLI-docs check; install hooks with
`uv run pre-commit install`.

### Golden-file tests

Integration tests compare generated output against committed `expected.puml`
files under `tests/fixtures/`. When you intentionally change output, regenerate
them, e.g.:

```bash
uv run erdify tests/fixtures/ecommerce --title 'E-Commerce ERD' -o tests/fixtures/ecommerce/expected.puml
```

### Ground-truth tests

Golden files only lock in erdify's own output. The ground-truth tests check it
against the real framework instead: `tests/ground_truth/` loads a model source
with the library (Django: an isolated app registry, no database) and reduces it
to the same normalised schema as erdify's parse (tables, columns, PK / unique /
FK, nullability, many-to-many edges, enums). `tests/test_ground_truth_django.py`
runs this over the Django fixture, `docs/examples/django`, the Django
**edge-case catalog** (`tests/fixtures/django_edge_cases/`, one module per
Django feature) and every inline Django snippet in `tests/test_*.py` (any
string literal with a `class` and `models.Model` or a `from django` import,
discovered automatically). A new regression test is checked against Django
without extra work.

- A mismatch is a bug in erdify (or in the source), not in the harness. Fix it,
  or file an issue and add the source to `KNOWN_DIFFERENCES` (a strict xfail).
  A limitation documented in `docs/frameworks/limitations.md` is listed in
  `LIMITATIONS` instead (also a strict xfail).
- Nothing is skipped silently: a source Django rejects or can't load fails the
  test unless it is listed, with a reason, in `EXPECTED_REJECTED` /
  `EXPECTED_UNLOADABLE`.
- Test data must be a model module a Django project can run: every source is
  loaded like a project (contrib apps installed, `AUTH_USER_MODEL` set to the
  source's own user model if it defines one) and must pass Django's model
  checks (the `models` checks of `manage.py check`, per model and across
  models). The edge-case catalog, the fixture app and the docs example always
  must; a regression snippet with a deliberate check error lists its error ids
  and the reason in `EXPECTED_CHECK_ERRORS`.
- New Django parsing support → add an edge-case module for it.
- CI repeats these tests on every supported Django series (`django` job in
  `test.yml`). Add a series there when Django releases one.

`tests/test_ground_truth_sqlalchemy.py` is the SQLAlchemy / SQLModel
counterpart (`tests/ground_truth/sqlalchemy_ref.py`): each source runs as a
fresh module (SQLModel's shared registry is swapped per load), its mappers are
configured, and the schema comes from `MetaData.tables` (every Core
`Table(...)` included) and the relationships from `sqlalchemy.inspect(Model)`
(target, `"one"` / `"many"`, optionality, `back_populates`; `secondary=` and
`backref=`-created sides are left out, as erdify draws them through the link
table / doesn't declare them). Sources: the SQLAlchemy / SQLModel fixtures, the
two docs examples, the **edge-case catalog** `tests/fixtures/sqlalchemy_edge_cases/`
and every inline SQLAlchemy / SQLModel snippet (a `HEADER + """..."""`
concatenation is folded into one source; `SNIPPET_HEADERS` names the header a
test helper prepends to a bare body).

- The same rules apply: a mismatch is an erdify bug (`KNOWN_DIFFERENCES` with
  an issue), a documented limitation is listed in `LIMITATIONS` (both strict
  xfails), and `EXPECTED_REJECTED` / `EXPECTED_UNLOADABLE` need a reason.
- Test data must configure (SQLAlchemy's own validation, what
  `configure_mappers()` does on first use): every relationship needs a foreign
  key to join on. A deliberate configuration error is listed in
  `EXPECTED_CHECK_ERRORS`; the fixtures, the docs examples and the catalog
  always must configure.
- New SQLAlchemy / SQLModel parsing support → add an edge-case module for it.
- CI repeats these tests on every supported SQLAlchemy series and on the
  oldest supported SQLModel (0.0.22) as well as the locked one (`sqlalchemy`
  job in `test.yml`). Where SQLModel changed what it builds, expectations are
  version-gated: `REQUIRES_SQLMODEL` (skip a catalog module before the release
  that added the feature) and `SQLMODEL_DIFFERENCES` (erdify follows the newest
  SQLModel; a known difference before the release that changed it).

`tests/test_ground_truth_sql.py` is the SQL DDL counterpart
(`tests/ground_truth/sqlite_ref.py`, stdlib `sqlite3`): each source runs in an
in-memory SQLite database, statement by statement, and the schema comes from
`PRAGMA table_xinfo` (columns, `notnull`, `pk`; a primary key counts as not
nullable, the SQL standard, not SQLite's legacy quirk), `foreign_key_list` (a
bare `REFERENCES t` is `t`'s primary key; names resolve case-insensitively)
and `index_list` / `index_info` (a single-column, non-partial unique index
makes a column unique). Enums are not compared (SQLite has none). Sources: the
SQL fixture, the `sql` block of `docs/frameworks/sql.md`, the **edge-case
catalog** `tests/fixtures/sql_edge_cases/` and every inline string with a
`CREATE TABLE`.

- The same rules apply: a mismatch is an erdify bug (`KNOWN_DIFFERENCES` with
  an issue); DDL SQLite can't run (`ALTER TABLE ... ADD CONSTRAINT`, a syntax
  error on purpose) is listed in `EXPECTED_REJECTED` with a reason.
- A source in another dialect is listed in `DIALECTS` (passed to erdify as
  `--sql-dialect`); only the statements SQLite rejects are transpiled by
  sqlglot, and a `CREATE TYPE` is dropped.
- Test DDL must pass SQLite's foreign-key check (the parent table exists, the
  parent key is a primary key or unique). A deliberate error is listed in
  `EXPECTED_CHECK_ERRORS`; the fixture, the docs example and the catalog
  always must pass.
- New SQL parsing support → add an edge-case file for it.

`tests/test_ground_truth_keyless.py` is the Pydantic / dataclass counterpart
(`tests/ground_truth/keyless_ref.py`): each source runs as a fresh module,
and the fields come from `Model.model_fields` (after `model_rebuild()`) and
`dataclasses.fields()` (types resolved in the class that declared the field),
inherited ones included. Compared: field names, nullability (the type admits
`None`; a default doesn't count) and nested-model references (target, one /
many, optional). Keys (`--infer-keys` only), table names and type display
strings are not. Sources: the Pydantic, dataclass and `scan_filter` fixtures,
the two docs examples, the **edge-case catalog**
`tests/fixtures/keyless_edge_cases/`, every inline snippet with a `class` and
`BaseModel` / `dataclass` (a source with SQLAlchemy, SQLModel or Django words
belongs to their harness), and every annotation a `str.format` template in
`TEMPLATES` is filled with by its parametrized tests.

- The same rules apply: a mismatch is an erdify bug (`KNOWN_DIFFERENCES` with
  an issue), a documented limitation is listed in `LIMITATIONS`, a source the
  library refuses on purpose in `EXPECTED_REJECTED` and one that is not
  self-contained in `EXPECTED_UNLOADABLE`, each with a reason.
- Test models must import what their annotations use; the fixtures, the docs
  examples and the catalog always must load.
- New Pydantic / dataclass parsing support → add an edge-case module for it.

- `.github/workflows/upstream.yml` (weekly, not a required check) runs the
  whole suite on the newest releases (newest SQLModel / Pydantic / sqlglot /
  Django from PyPI on top of `uv lock --upgrade`) and
  `scripts/check_upstream_series.py`, which fails when a Django / SQLAlchemy
  series is out but missing from the `test.yml` matrices. A failed scheduled
  run opens or updates one `ci`-labelled issue.

### Supported versions are documented

`docs/installation.md` ("Supported framework versions") is the single list of
the Python, SQLModel, SQLAlchemy, Django, Pydantic and sqlglot versions erdify
supports and what CI checks for each. It must always match the CI matrices in
`test.yml`: adding or dropping a version updates the table, the matrix and the
changelog in the same change (policy: `docs/stability.md`).

## Architecture

erdify turns Python model files into ERD diagrams **without importing them or
touching a database** — it parses source with the stdlib `ast` module and has
**zero runtime dependencies**. Keep it that way: do not add runtime deps.

The pipeline is a clean three-stage flow, wired together by the CLI:

```
parser/    ──►  config.py (IR)  ──►  generator.py
(AST scan)      EntityInfo/         PlantUML / Mermaid /
                EnumInfo/           JSON / HTML
                FieldInfo
```

- **`parser/`** — the Python model frontend. `erdify.parser` re-exports what
  `erdify` and the CLI use; the package and its submodules are internal (the
  stable surface is `erdify.__all__`).
  - `core.py`: `parse_models_directory()` and `ASTDatabaseParser`, which runs
    the passes: collect every class, classify it, build entities, add Core
    tables, apply `--exclude`.
  - `discovery.py`: finds model files (glob `include_patterns`, default
    `models.py`; prunes `DEFAULT_EXCLUDE_DIRS` *during* the walk for speed).
  - `dialects/`: one `Dialect` per framework (`base.py` has the interface, its
    hooks and `ParseContext`). Every class is classified into exactly one of
    `MODEL_SOURCES` (`sqlmodel`, `sqlalchemy`, `django`, `dataclass`,
    `pydantic`) by trying the dialects of the `DIALECTS` registry **in that
    order**; `MODEL_SOURCES` is derived from it. Shared code never checks a
    framework name: a framework differs only through its `Dialect` hooks. The dialect of the
    concrete model reads its body *and every ancestor's*: a mixin is read the
    way the model that inherits it is. SQLModel, SQLAlchemy, Pydantic and
    dataclass share `annotated.py` (annotated class bodies); Django has its own.
  - `inheritance.py`: `ClassIndex` (MRO, merge order, listing order) and member
    merging, shared by all dialects; dialects adjust it through the `Dialect`
    hooks in `dialects/base.py` (`merge`, `drop_on_merge`, `self_owner`, …).
  - `aliases.py`: `AliasResolver`, SQLAlchemy column type aliases
    (`intpk = Annotated[int, mapped_column(...)]`) resolved per module like
    Python names (bindings, imports into scanned files, derived aliases).
  - `annotations.py`: pure helpers that read annotations from the syntax tree
    (model references, column type and nullability).

  Link tables are detected **structurally** (a composite PK made up entirely of
  FKs, with no payload columns — two FKs or more), not by name.

- **`sql_parser.py`** — the optional SQL DDL frontend (`erdify[sql]`).
  `SqlSchemaParser` turns `CREATE TABLE` / `CREATE TYPE ... AS ENUM` /
  `CREATE INDEX` / `ALTER TABLE ... FOREIGN KEY` into the same IR, with
  `source="sql"`. `sqlglot` is imported lazily inside `parse()` — never at module
  import time (a test enforces this) — and a missing install raises
  `SqlDependencyError`. `parse_models_directory()` calls it for any `.sql` files
  matched by the include patterns, so one input can mix Python models and DDL.

- **`config.py`** — `FieldInfo`, `EnumInfo`, `EntityInfo` dataclasses. This is the
  framework-agnostic intermediate representation that decouples parsing from
  rendering. The parser produces it; the generators consume it.

- **`generator.py`** — `_ERGenerator` base with `PlantUMLGenerator` and
  `MermaidGenerator` subclasses, plus the `generate_plantuml/mermaid/json/html`
  functions. All four formats render from the same IR.

- **`cli.py`** — argparse parser (`build_parser()`, also reused by the docs
  script) + `main()`. The `FORMATS` dict maps format name → (generator, extension).
  Settings precedence is **explicit CLI flag > `[tool.erdify]` config > default**,
  implemented by the `pick()` helper; boolean flags merge by OR.

- **`pyproject.py`** — `load_config()` finds the nearest `pyproject.toml`
  (searching upward from the input) and reads/validates the `[tool.erdify]` table.
  Recognized keys mirror the CLI options.

- **`inject.py`** — `--inject` embeds the diagram into a Markdown file between
  `<!-- erdify:start -->` / `<!-- erdify:end -->` markers; only that region is
  rewritten.

The public Python API is whatever `src/erdify/__init__.py` re-exports.

## Conventions

- **Python ≥ 3.11**, mypy `--strict`, ruff line length 100.
- **Conventional Commits**: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`,
  `style:`, `chore:`.
- Google-style docstrings on public modules, classes, and functions.
- Releases: a release PR (title `chore: release X.Y.Z`, label `release`, body
  from `.github/release-pr-template.md`) bumps the version, moves the CHANGELOG entries
  and runs `uv lock`; after merge, publishing a GitHub Release
  (`gh release create vX.Y.Z --target <full SHA>`) runs `publish.yml`, gated
  by the `pypi` environment. A pushed tag alone publishes nothing. The version
  is single-sourced from package metadata via `importlib.metadata`.
- Every PR fills in its template (`.github/PULL_REQUEST_TEMPLATE.md`; release
  PRs `.github/release-pr-template.md`); the `PR description` check
  (`scripts/check_pr_description.py`) enforces it.
- New framework parsing → add a `Dialect` subclass under `parser/dialects/` and
  register it in `DIALECTS` (its position is its classification order), add a
  fixture dir under `tests/fixtures/` and wire it into the integration tests.

## Keep everything in sync

A user-facing change usually touches more than the code. Whenever a feature,
flag, default, or supported-version changes — and especially before tagging a
release — check that all of these still agree, and update whatever has drifted:

- `CHANGELOG.md` — an entry under `[Unreleased]` (Keep a Changelog format); on
  release, move it under the new version and update the compare-link footer.
- `README.md` — features list and any examples.
- `docs/` (mkdocs site) — including `docs/features.md` (the feature matrix) and
  `docs/usage/cli.md` (regenerate with `scripts/gen_cli_docs.py`); add new pages
  to the `nav` in `mkdocs.yml`.
- `CONTRIBUTING.md` — commands, supported Python versions, project structure.
- `pyproject.toml` — `requires-python`, classifiers, keywords.

Classify every change against `docs/stability.md` (the versioning policy) and file
its changelog entry under the matching heading: `### Changed — **breaking**`,
`### Deprecated`, or `### Output changes`. Use `### Output changes` when the
generated diagram text changes (it makes `--check` fail once after upgrading).

The feature matrix and CLI flags are the parts that drift most often. When in
doubt, verify a claimed feature against the code (`parser/dialects/` for detection,
`generator.py` for what's actually rendered) before documenting it.
