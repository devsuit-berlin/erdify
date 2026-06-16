# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.7.1] - 2026-06-16

### Changed

- Documentation now lives at a dedicated site, **<https://erdify.devsuit.io>**
  (MkDocs Material, auto-deployed). The README links point there and its footer
  credits devsuit GmbH. No code changes — this release refreshes the published
  project metadata/README.

## [0.7.0] - 2026-06-16

### Added

- `--format json` — emit the parsed model (entities, columns with PK/FK/nullable/
  default, relationships, enums) as structured JSON, so downstream tools can
  consume erdify's model without re-parsing.
- `--format html` — wrap the Mermaid diagram in a self-contained HTML page
  (pinned Mermaid CDN) that renders in a browser. Composes with multi-format
  output, `--check` and `[tool.erdify]` like the other formats.

## [0.6.0] - 2026-06-16

### Added

- Mermaid output via `--format` (`plantuml` and/or `mermaid`). Mermaid
  `erDiagram` renders natively in GitHub/GitLab markdown. `--format` accepts
  multiple values; with `-o` the file extension is set per format (`.puml` /
  `.mmd`) and multiple formats are written side by side; `--check` validates all
  targets. Configurable via `format` in `[tool.erdify]`.
- Configuration via `[tool.erdify]` in `pyproject.toml`. erdify reads the nearest
  `pyproject.toml` (searching upward from the input) for `title`, `output`,
  `sources`, `exclude`, `exclude_paths`, `infer_keys`, `django_raw_types`,
  `no_enums`, `no_relationships` and `no_default_excludes`. Precedence is explicit
  CLI flag > config value > default; a relative `output` resolves from the project
  root.
- `--check` mode: regenerate in memory and compare to the `--output` file without
  writing, exiting non-zero if it is missing or stale — for CI / pre-commit drift
  checks.
- Django `models.TextChoices` / `models.IntegerChoices` classes are now rendered
  as enums, and a field referencing one via `choices=Status.choices` (or
  `choices=Status`) is linked to that enum. Inline `choices=[("a", "A"), …]`
  tuples are anonymous and not rendered.

### Changed

- **Minimum Python is now 3.11** (was 3.10), enabling the stdlib `tomllib` parser
  for `[tool.erdify]` config with no new runtime dependency.
- Documentation restructured: the README is slimmed to a quickstart, the
  framework showcase and feature overview, with the detailed reference (CLI,
  filtering, viewing, CI, framework specifics) moved into a `docs/` tree.

## [0.5.0] - 2026-06-16

### Added

- Path-based scan filtering. `models.py` files under common non-project
  directories (`site-packages`, `.venv`, `venv`, `node_modules`, `__pycache__`,
  `.git`, …) are now auto-skipped, so running on a Django project picks up only
  your own apps and not installed third-party packages. `--exclude-paths` skips
  additional folders by path/segment glob (e.g. `--exclude-paths migrations
  legacy`), and `--no-default-excludes` disables the built-in skip list. Unlike
  `--exclude` (which filters by class/table name after parsing), this filters
  files before the scan.
- Django ORM is now a supported model source. `models.Model` subclasses become
  entities; columns, `primary_key=True` / implicit `id`, `ForeignKey` (N:1),
  `OneToOneField` (1:1) and `ManyToManyField` (M:N, including `through=`) are
  translated. `class Meta: db_table` overrides the table name and `class Meta:
  abstract = True` bases are inherited but not drawn; `"self"` and `"app.Model"`
  relationship targets are resolved. Django participates in `--sources` (the
  `django` kind). Field types are mapped to readable Python types by default
  (`CharField` → `str`, `AutoField` → `int`, `DateTimeField` → `datetime`, …),
  with ambiguous/unknown fields falling back to their Django name; pass
  `--django-raw-types` to show the original Django field names instead.

## [0.4.2] - 2026-06-16

### Fixed

- Link tables are now detected **structurally** — an entity whose columns are
  exactly two foreign keys, both part of the primary key — instead of by the
  `*Link*` class-name heuristic. Association tables not named `*Link*` (e.g.
  `PostTag`) are now drawn as a proper M:N path, and normal entities that merely
  contain "Link" in their name (e.g. `LinkPreview`) are no longer misclassified
  as link tables (#35).
- A SQLAlchemy `relationship(secondary=Table(...))` that references a module-level
  Core `Table(...)` (rather than a mapped link-table class) is now modelled: the
  association table is synthesized into a link entity and the M:N is drawn through
  it. Previously the table was not parsed at all, so the relationship was dropped
  and the two endpoints were left disconnected (#34).
- Columns with no known type (an untyped Core `Column`) no longer render a
  dangling `:` with an empty type.

## [0.4.1] - 2026-06-15

### Fixed

- Many-to-many relationships declared via `Relationship(link_model=...)`
  (SQLModel) or `relationship(secondary=...)` (SQLAlchemy) no longer emit a
  spurious, mis-cardinalized direct edge between the two endpoints. The
  association is drawn solely through the link table. Such relationships are
  skipped during parsing, and the generator also suppresses any direct edge for
  entity pairs already joined by a link table.

## [0.4.0] - 2026-06-15

### Added

- `--sources` flag to restrict which model kinds become entities (`sqlmodel`,
  `sqlalchemy`, `dataclass`, `pydantic`). Default is unchanged (all kinds). Use
  `--sources sqlmodel sqlalchemy` for a pure DB-table ERD that excludes Pydantic
  DTOs and `@dataclass` query wrappers by kind rather than by name.

### Fixed

- Type strings for generic columns lost their closing bracket (`list[str]` was
  rendered as `list[str`). The optional-wrapper cleanup no longer strips every
  `]`; it unwraps only a leading `Optional[...]`.

## [0.3.1] - 2026-06-15

### Changed

- Packaging: dev tooling is no longer published as installable extras. The
  `[project.optional-dependencies]` table was removed (it surfaced
  `mypy`/`pytest`/`pytest-cov`/`ruff`/`sqlmodel` as public `erdify[dev]` extras
  on PyPI); dev dependencies now live solely in the PEP 735 `[dependency-groups]`
  table. No change to runtime dependencies — erdify still has none.

### Internal

- Added `sqlalchemy` and `pydantic` as explicit dev dependencies (previously
  only pulled in transitively via `sqlmodel`).
- Added a fixture smoke test that imports every non-malformed test fixture to
  guard against fixtures rotting into non-importable code.

## [0.3.0] - 2026-06-12

First public PyPI release. Extends erdify well beyond SQLModel into a
multi-framework ERD generator, and adds the tooling and project setup for
open-source maintenance.

### Added

- **SQLAlchemy 2.0 support** — parse `Mapped[...]` / `mapped_column()` models,
  including positional `ForeignKey(...)` and lowercase `relationship()`. Mixins
  and abstract bases are inherited but not drawn. Detected automatically.
- **Pydantic support** — every `BaseModel` subclass (including transitive)
  becomes an entity; fields typed as another model become relationships.
- **Dataclass support** — every `@dataclass` becomes an entity; nested model
  references become relationships.
- `--exclude` — exclude entities by case-sensitive glob matched against the
  class name or table name; dangling relationships to excluded entities are
  dropped.
- `--infer-keys` — opt-in name heuristic for keyless models (Pydantic/dataclass):
  `id` → primary key, `<x>_id` → foreign key targeting table `<x>`. Does not
  affect SQLModel/SQLAlchemy.
- Framework comparison docs with runnable examples in `docs/examples/` (the same
  schema in all four frameworks renders an identical ERD).

### Changed

- `--exclude` is now implemented (previously a no-op placeholder).
- The package version is single-sourced from the installed metadata
  (`importlib.metadata`); `erdify --version` and `erdify.__version__` no longer
  hardcode the number.
- Project metadata: SPDX `license = "MIT"` (PEP 639), updated description and
  keywords, added `devsuit GmbH` as author.

### Fixed

- `mypy --strict` passes with no errors; type checking is enforced in CI.

### Internal

- CI test matrix covers Python 3.10–3.15 (3.15 pre-release, non-blocking);
  coverage gate at 90%.
- Release publishing via GitHub Actions with the version stamped from the release
  tag (`vX.Y.Z` → `X.Y.Z`); a manual TestPyPI dry-run workflow.

## [0.1.0]

### Added

- Initial release: generate PlantUML ERD diagrams from SQLModel models via AST.

[Unreleased]: https://github.com/devsuit-berlin/erdify/compare/v0.7.1...HEAD
[0.7.1]: https://github.com/devsuit-berlin/erdify/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/devsuit-berlin/erdify/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/devsuit-berlin/erdify/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/devsuit-berlin/erdify/compare/v0.4.2...v0.5.0
[0.4.2]: https://github.com/devsuit-berlin/erdify/compare/v0.4.1...v0.4.2
[0.4.1]: https://github.com/devsuit-berlin/erdify/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/devsuit-berlin/erdify/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/devsuit-berlin/erdify/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/devsuit-berlin/erdify/compare/v0.1.0...v0.3.0
[0.1.0]: https://github.com/devsuit-berlin/erdify/releases/tag/v0.1.0
