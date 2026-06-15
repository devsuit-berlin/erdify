# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/devsuit-berlin/erdify/compare/v0.3.1...HEAD
[0.3.1]: https://github.com/devsuit-berlin/erdify/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/devsuit-berlin/erdify/compare/v0.1.0...v0.3.0
[0.1.0]: https://github.com/devsuit-berlin/erdify/releases/tag/v0.1.0
