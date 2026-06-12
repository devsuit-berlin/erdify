# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Release publishing uses token auth (`PYPI_API_TOKEN` / `PYPI_TEST_API_TOKEN`);
  the published version is stamped from the release tag (`vX.Y.Z` → `X.Y.Z`).
- CI test matrix extended to Python 3.14 and 3.15 (3.15 pre-release, non-blocking).

## [0.2.0]

### Added

- **SQLAlchemy 2.0 support** — parse `Mapped[...]` / `mapped_column()` models,
  including positional `ForeignKey(...)` and lowercase `relationship()`.
  Detected automatically.
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
- Framework comparison docs with runnable examples in `docs/examples/`.

### Changed

- The package version is now single-sourced from the installed metadata
  (`importlib.metadata`); `erdify --version` and `erdify.__version__` no longer
  hardcode the number.
- `--exclude` is now implemented (previously a no-op placeholder).
- Project metadata: SPDX `license = "MIT"` (PEP 639), updated description and
  keywords.

### Fixed

- `mypy --strict` now passes with no errors; type checking is enforced in CI.

## [0.1.0]

### Added

- Initial release: generate PlantUML ERD diagrams from SQLModel models via AST.

[Unreleased]: https://github.com/devsuit-berlin/erdify/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/devsuit-berlin/erdify/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/devsuit-berlin/erdify/releases/tag/v0.1.0
