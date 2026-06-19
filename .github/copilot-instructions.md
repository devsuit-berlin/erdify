# Copilot / AI agent instructions

This is the single source of truth for AI-agent and contributor guidance in this
repository. `CLAUDE.md` and `AGENTS.md` point here.

## Language policy

**The entire project scope is English-only.** This applies to code, comments,
docstrings, documentation, commit messages, PR titles and descriptions, release
notes, changelog entries, announcements, and issues. No exceptions, regardless
of the language a request is written in.

## Commands

This project uses [uv](https://docs.astral.sh/uv/). All commands run through `uv run`.

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

## Architecture

erdify turns Python model files into ERD diagrams **without importing them or
touching a database** — it parses source with the stdlib `ast` module and has
**zero runtime dependencies**. Keep it that way: do not add runtime deps.

The pipeline is a clean three-stage flow, wired together by the CLI:

```
parser.py  ──►  config.py (IR)  ──►  generator.py
(AST scan)      EntityInfo/         PlantUML / Mermaid /
                EnumInfo/           JSON / HTML
                FieldInfo
```

- **`parser.py`** — `parse_models_directory()` discovers model files (glob
  `include_patterns`, default `models.py`; prunes `DEFAULT_EXCLUDE_DIRS` *during*
  the walk for speed) and `ASTDatabaseParser` walks each file's AST. Every class
  is classified into exactly one of `MODEL_SOURCES`
  (`sqlmodel`, `sqlalchemy`, `django`, `dataclass`, `pydantic`) **in that order**,
  then its fields/relationships/enums are extracted. This is the largest and most
  intricate module — framework-specific parsing logic lives here. Link tables are
  detected **structurally** (an entity whose columns are exactly two FKs that are
  both part of the PK), not by name.

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
- Releases are tag-driven: pushing a `vX.Y.Z` tag publishes to PyPI; the version
  is single-sourced from package metadata via `importlib.metadata`.
- New framework parsing → add a fixture dir under `tests/fixtures/` and wire it
  into the integration tests.

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

The feature matrix and CLI flags are the parts that drift most often. When in
doubt, verify a claimed feature against the code (`parser.py` for detection,
`generator.py` for what's actually rendered) before documenting it.
