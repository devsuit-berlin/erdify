# Contributing to erdify

Thank you for considering a contribution to erdify.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Making Changes](#making-changes)
- [Testing](#testing)
- [Submitting Changes](#submitting-changes)
- [Style Guide](#style-guide)

## Code of Conduct

This project and everyone participating in it is governed by our commitment to providing a welcoming and inclusive environment. Please be respectful and constructive in all interactions.

## Getting Started

### Prerequisites

- Python 3.11 or higher (CI tests 3.11–3.15)
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- Git

### Finding Something to Work On

- **Bug fixes**: Check the [issues](https://github.com/devsuit-berlin/erdify/issues) labeled `bug`
- **Features**: Look for issues labeled `enhancement`
- **Documentation**: Help improve our docs
- **Tests**: Increase test coverage

## Development Setup

### 1. Fork and Clone

```bash
# Fork the repository on GitHub, then:
git clone https://github.com/YOUR_USERNAME/erdify.git
cd erdify
```

### 2. Set Up Environment

Using uv (recommended):

```bash
# Install uv if you haven't
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create virtual environment and install dependencies
uv sync

# To work on the SQL DDL frontend, include the optional sql extra:
uv sync --extra sql
```

Using pip:

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

### 3. Verify Setup

```bash
# Run tests
uv run pytest

# Run type checking
uv run mypy src/

# Run linting
uv run ruff check src/ tests/
```

## Making Changes

### 1. Create a Branch

```bash
git checkout -b feature/your-feature-name
# or
git checkout -b fix/your-bug-fix
```

### 2. Project Structure

```bash
erdify/
├── src/erdify/
│   ├── __init__.py      # Public API exports
│   ├── __main__.py      # python -m entry point
│   ├── cli.py           # Command-line interface (argparse + main)
│   ├── config.py        # Data classes / IR (FieldInfo, EnumInfo, EntityInfo)
│   ├── generator.py     # PlantUML / Mermaid / JSON / HTML generation
│   ├── inject.py        # Markdown embedding (--inject)
│   ├── pyproject.py     # [tool.erdify] config loading
│   ├── parser/          # AST parsing of Python models
│   │   ├── core.py          # ASTDatabaseParser + parse_models_directory / scan_report
│   │   ├── discovery.py     # File discovery (include globs, exclude paths)
│   │   ├── aliases.py       # Column type aliases, resolved per module
│   │   ├── annotations.py   # Reading type annotations from the syntax tree
│   │   ├── inheritance.py   # MRO, merge order, member merging (all frameworks)
│   │   ├── common.py        # Shared types and small helpers
│   │   └── dialects/        # One Dialect class per framework (detection + class bodies)
│   │       ├── __init__.py      # DIALECTS registry (classification order) + MODEL_SOURCES
│   │       ├── base.py          # Dialect interface, its hooks, ParseContext
│   │       ├── annotated.py     # Shared reader for annotated class bodies
│   │       ├── sqlalchemy.py    # SQLModel, SQLAlchemy ORM, Core tables
│   │       ├── keyless.py       # Pydantic, dataclass
│   │       └── django.py        # Django ORM
│   └── sql_parser.py    # SQL DDL frontend (optional, erdify[sql] / sqlglot)
├── tests/
│   ├── fixtures/        # Test model files (one dir per scenario/framework)
│   ├── ground_truth/    # Loads model sources with the real framework for comparison
│   ├── conftest.py      # Pytest fixtures
│   └── test_*.py        # Unit + integration tests
└── pyproject.toml
```

### 3. Make Your Changes

- Keep changes focused and atomic
- Follow the existing code style
- Add/update tests for your changes
- Update documentation if needed

## Testing

### Running Tests

```bash
# Run all tests
uv run pytest

# Run with verbose output
uv run pytest -v

# Run specific test file
uv run pytest tests/test_parser.py

# Run with coverage
uv run pytest --cov=erdify --cov-report=html
```

### Writing Tests

- Place tests in the appropriate `test_*.py` file
- Use descriptive test names: `test_parse_foreign_key_with_custom_table`
- Use fixtures from `conftest.py` when possible

### Golden File Tests

For integration tests, we use golden files (expected output files):

```bash
# If you intentionally change the output format, update golden files:
erdify tests/fixtures/ecommerce --title 'E-Commerce ERD' -o tests/fixtures/ecommerce/expected.puml
```

### Ground-Truth Tests

Golden files only show that the output didn't change. The ground-truth tests
check that it is *right*: `tests/test_ground_truth_django.py` loads every Django
model source the suite uses (fixtures, `docs/examples/django`, the edge-case
catalog in `tests/fixtures/django_edge_cases/`, and every inline snippet in
`tests/test_*.py`) with Django itself and compares the schema Django builds with
erdify's parse. A Django snippet you add to a test is picked up automatically.
If it shows a real erdify bug you aren't fixing in the same change, open an
issue and list the source in `KNOWN_DIFFERENCES`; a documented limitation goes in
`LIMITATIONS`. A source Django can't load or
rejects must be listed in `EXPECTED_UNLOADABLE` / `EXPECTED_REJECTED`; nothing is
skipped silently.

Test models must also be valid Django: each source is loaded the way a project
would run it and must pass Django's model checks (the `models` checks of
`manage.py check`, per model and across models) on every supported Django series. Give a second foreign key to the same model a
`related_name`, a `CharField` a `max_length`, and so on. A regression snippet that
violates a check on purpose lists the error ids and why in
`EXPECTED_CHECK_ERRORS`.

```bash
uv run pytest tests/test_ground_truth_django.py -rsx
# Against another Django series:
uv run --with "django~=6.1.0" pytest tests/test_ground_truth_django.py
```

`tests/test_ground_truth_sqlalchemy.py` does the same for SQLAlchemy and
SQLModel: every source (the SQLAlchemy / SQLModel fixtures,
`docs/examples/sqlalchemy` and `docs/examples/sqlmodel`, the edge-case catalog
in `tests/fixtures/sqlalchemy_edge_cases/`, and every inline snippet) is
executed, its mappers are configured, and `MetaData.tables` plus
`sqlalchemy.inspect(Model).relationships` are compared with erdify's parse,
relationships included (cardinality, optionality, `back_populates`). A snippet
built as `HEADER + """..."""` is folded into one source; a body that a test
helper prefixes gets that file's header from `SNIPPET_HEADERS`. Test models
must configure, as on first use in a project: give each relationship a foreign
key to join on, and `foreign_keys=` where there are several. Documented
limitations are listed in `LIMITATIONS`, so they show up once supported.

```bash
uv run pytest tests/test_ground_truth_sqlalchemy.py -rsx
# Against another SQLAlchemy series:
uv run --with "sqlalchemy~=2.0.0" pytest tests/test_ground_truth_sqlalchemy.py
# Against the oldest supported SQLModel (it requires SQLAlchemy < 2.1):
uv run --with "sqlmodel==0.0.22" --with "sqlalchemy~=2.0.0" pytest tests/test_ground_truth_sqlalchemy.py
```

Where SQLModel changed what it builds in a release, the expectation depends on
the installed version: `REQUIRES_SQLMODEL` skips a catalog module before the
release that added its feature, and `SQLMODEL_DIFFERENCES` holds known
differences before a release: erdify follows the newest SQLModel.

`tests/test_ground_truth_sql.py` checks the SQL DDL frontend against SQLite
(stdlib `sqlite3`, no extra dependency): every DDL source (`tests/fixtures/sql`,
the example in `docs/frameworks/sql.md`, the edge-case catalog in
`tests/fixtures/sql_edge_cases/`, and every inline string with a
`CREATE TABLE`) runs in an in-memory database, and `PRAGMA table_xinfo` /
`foreign_key_list` / `index_list` are compared with erdify's parse. The DDL is
run as written; a source in another dialect is listed in `DIALECTS`, and only
the statements SQLite rejects are transpiled by sqlglot. Test DDL must pass
SQLite's foreign-key check (the parent table exists, the parent key is a
primary key or unique); a deliberate error is listed in `EXPECTED_CHECK_ERRORS`,
DDL SQLite can't run (`ALTER TABLE ... ADD CONSTRAINT`) in `EXPECTED_REJECTED`.

```bash
uv run pytest tests/test_ground_truth_sql.py -rsx
```

`tests/test_ground_truth_keyless.py` checks Pydantic models and dataclasses:
every source (`tests/fixtures/pydantic`, `tests/fixtures/dataclasses`,
`tests/fixtures/scan_filter`, `docs/examples/pydantic` and
`docs/examples/dataclass`, the edge-case catalog in
`tests/fixtures/keyless_edge_cases/`, every inline snippet, and every
annotation a template in `TEMPLATES` is filled with) is executed, and
`Model.model_fields` / `dataclasses.fields()` are compared with erdify's
parse: field names, whether a field admits `None`, enums, and which fields name
another model (target, one / many, optional). Keys, table names and type
display strings are not compared; they are erdify's own. Test models must be
importable: give a template every import its annotations use. A source the
library refuses on purpose is listed in `EXPECTED_REJECTED`, one that is not
self-contained in `EXPECTED_UNLOADABLE`; a real erdify bug you aren't fixing
goes in `KNOWN_DIFFERENCES` with an issue, a documented limitation in
`LIMITATIONS`.

```bash
uv run pytest tests/test_ground_truth_keyless.py -rsx
```

The supported framework versions are listed in `docs/installation.md`
("Supported framework versions"). When you add or drop one, update that table,
the CI matrix in `.github/workflows/test.yml`, and the changelog together.
A scheduled workflow (`.github/workflows/upstream.yml`, weekly) runs the
suite on the newest releases and reports a Django or SQLAlchemy series that is
missing from the matrix; you can also start it by hand from the Actions tab.
Check for new series locally with:

```bash
uv run --no-project --with pyyaml --with packaging python scripts/check_upstream_series.py
```

### Real Renderers and the JSON Schema

String comparisons can't tell whether a renderer accepts the output. The CI job
`renderers` writes every fixture, edge-case catalog module and docs example
in every format (`scripts/render_outputs.py`), checks the `.puml` files with
PlantUML (`-checkonly`), and renders the `.mmd` files and every HTML page with
the real Mermaid in headless Chromium (`scripts/renderers/check.mjs`; the
page's CDN request is answered by the pinned local Mermaid, any other request
is blocked). `tests/test_json_schema.py` validates the JSON of the same
sources against `docs/schema/output-v1.json`, and checks that the keys erdify
emits, the schema and the tables in `docs/usage/output-formats.md` agree: a
new JSON key goes into all three. A new fixture directory or catalog module is
picked up automatically; one that needs a SQL dialect (as in the SQL
ground-truth `DIALECTS`, a test checks they agree) or `--base-classes` is
listed in `render_outputs.py`, and one with nothing to draw in its
`NO_DIAGRAM`. Chromium comes from the build the pinned Puppeteer selects (no
checksum of our own); it only renders erdify's output, with the network
blocked. PlantUML is pinned and checksum-verified in the workflow.

Run the renderer check locally (needs Java and Node):

```bash
uv run python scripts/render_outputs.py /tmp/erdify-out
plantuml -checkonly -failfast2 /tmp/erdify-out/*.puml   # or java -jar plantuml.jar ...
cd scripts/renderers && npm ci --ignore-scripts \
  && npx --no-install puppeteer browsers install chrome-headless-shell \
  && node check.mjs /tmp/erdify-out
```

### Adding New Test Fixtures

1. Create a new directory under `tests/fixtures/`
2. Add a `models.py` with definitions in any supported framework (SQLModel,
   SQLAlchemy, Django, Pydantic, or dataclasses)
3. Generate the expected output:

   ```bash
   erdify tests/fixtures/your_fixture -o tests/fixtures/your_fixture/expected.puml
   ```

4. Add the fixture to `test_integration.py`

SQL DDL test fixtures live in `tests/fixtures/sql/` — each subdirectory contains
one or more `.sql` files and the corresponding expected output. Make sure you have
the `[sql]` extra installed (`uv sync --extra sql`) before running the SQL tests.

## Submitting Changes

### 1. Ensure Quality

```bash
# Format code
uv run ruff format src/ tests/

# Check linting
uv run ruff check src/ tests/

# Run type checking
uv run mypy src/

# Run all tests
uv run pytest
```

Add a `CHANGELOG.md` entry under `[Unreleased]`. Check the change against the
[Stability & Versioning](https://erdify.devsuit.io/stability/) policy and file it
under the right heading:

- `### Changed — **breaking**` for anything the policy calls breaking.
- `### Deprecated` for something you deprecate.
- `### Output changes` for changes to the generated diagram text, because they
  make `--check` fail once after upgrading.

### 2. Commit Your Changes

We follow [Conventional Commits](https://www.conventionalcommits.org/):

```bash
git add .
git commit -m "feat: add support for composite primary keys"
# or
git commit -m "fix: handle nullable foreign keys correctly"
# or
git commit -m "docs: improve CLI usage examples"
```

**Commit Types:**

- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `test`: Adding/updating tests
- `refactor`: Code refactoring
- `style`: Formatting changes
- `chore`: Maintenance tasks

### 3. Push and Create PR

```bash
git push origin feature/your-feature-name
```

Then open a Pull Request on GitHub. The description is pre-filled from
[`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md); fill in
every section. The **PR description** check fails while Summary, Related
issues or How it was tested is empty, no box is ticked under Type of change,
or Output impact doesn't have exactly one ticked box. It re-runs when you edit the description.

- Title in Conventional Commits form (`fix: ...`, `feat: ...`)
- Link every issue the PR resolves ("Closes #123")

Release PRs (maintainers, title `chore: release X.Y.Z`) use the release
template: `gh pr create --label release --body-file .github/release-pr-template.md`.

## Style Guide

### Python Code

- Follow [PEP 8](https://pep8.org/)
- Use type hints for all public functions
- Maximum line length: 100 characters
- Use `ruff` for formatting and linting

### Documentation

- Use docstrings for all public modules, classes, and functions
- Follow [Google style docstrings](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings)
- Keep README and other docs up to date

### Example Docstring

```python
def parse_models_directory(
    path: Path, exclude_patterns: list[str] | None = None
) -> tuple[dict[str, EntityInfo], dict[str, EnumInfo]]:
    """
    Parse all SQLModel models in a directory.

    Args:
        path: Path to directory containing model files.
        exclude_patterns: List of glob patterns to exclude.

    Returns:
        Tuple of (entities dict, enums dict).

    Raises:
        FileNotFoundError: If path does not exist.

    Example:
        >>> entities, enums = parse_models_directory(Path("./models"))
        >>> print(len(entities))
        5
    """
```

## Tips

- **Small PRs are better**: They're easier to review and merge
- **Ask questions**: Open an issue if you're unsure about something
- **Test edge cases**: Think about what could go wrong
- **Update docs**: If you add a feature, document it

## Thank You

Every contribution helps make erdify better. We appreciate your time and effort.
