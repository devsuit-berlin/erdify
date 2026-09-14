# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.14.1] - 2026-09-14

### Fixed

- erdify now recognises ninja-style `ModelSchema` classes — those taking their
  fields from a Django model via an inner `Meta` (django-ninja) or `Config`
  (ninja-schema) — and **skips them with an explanatory warning** instead of
  drawing an entity with no fields. Naming `ModelSchema` via `--base-classes`
  previously produced an empty box beside the real table, which was worse than
  no support at all. Detection is narrow: only an inner `Meta`/`Config` that
  assigns `model` counts, so an ordinary Pydantic model with a nested config
  class and Django's own `class Meta` are both untouched. Resolving those
  schemas properly remains open in
  [#171](https://github.com/devsuit-berlin/erdify/issues/171).
- `docs/examples/frameworks.svg` is well-formed XML again. Its header comment
  contained a command-line flag, and XML comments may not contain a double
  hyphen, so the file failed to parse — harmless for the site, which serves the
  PNG, but the file documented as "the editable source" would not open in a
  browser or vector editor.
- The image footer reads "and raw SQL DDL" rather than listing it as a sixth
  bullet. The headline counts five *frameworks*; SQL DDL is an input format, and
  the flat list made the two numbers look like they disagreed.

### Changed

- The README and the documentation home page now open with a "five frameworks,
  one diagram" image — the same `User`/`Order` schema written in SQLModel,
  SQLAlchemy, Django, Pydantic and dataclasses, converging on the ERD they all
  produce. The previous image was the bare ERD under a caption claiming five
  frameworks, which the picture itself never showed. The snippets are taken
  from the runnable examples in `docs/examples/`, and it is drawn in the devsuit
  brand palette. `docs/examples/frameworks.svg` is the editable source; the
  now-unreferenced `docs/examples/erd.png` is removed.

## [0.14.0] - 2026-09-14

### Added

- `--base-classes NAME [NAME ...]` (and `base_classes` in `[tool.erdify]`) names
  extra base classes to treat as Pydantic models. Pydantic detection resolves
  ancestors only across the scanned files, so a base defined in an installed
  package — `ninja.Schema` from django-ninja — or in an internal library that
  `--include` does not match was unresolvable, and every subclass of it was
  silently skipped. Both the bare (`Schema`) and qualified (`ninja.Schema`)
  forms are matched, and intermediate bases defined in scanned files still
  resolve transitively. Partially addresses
  [#171](https://github.com/devsuit-berlin/erdify/issues/171); the
  `ModelSchema` variants, whose fields come from an inner `Meta`/`Config`
  rather than the class body, remain unsupported.

### Fixed

- The comparison page and the README comparison table were wrong about two
  rows. Both claimed no alternative ships a Markdown-injection or a CI
  drift-check feature; [paracelsus](https://github.com/tedivm/paracelsus) ships
  both, along with `[tool.paracelsus]` configuration and Mermaid output. It is
  now a column in the comparison table and a named entry under "when to use
  something else": it reaches models by importing them (`--import-module`), so
  it sees the fully-resolved metadata an AST scan cannot, and for a
  single-SQLAlchemy project that accuracy may be worth more than erdify's
  independence.

## [0.13.0] - 2026-09-14

### Changed — **breaking**

- **A run that finds no tables now exits `1` instead of `0`**, and writes
  nothing. Up to 0.12.3 it warned, wrote a structurally valid but empty
  diagram, and exited `0` — so a CI job that commits the regenerated ERD
  silently replaced a good diagram with an empty one whenever `--include`
  stopped matching, which a rename or a moved package is enough to cause. The
  overwhelmingly likely cause of zero entities is a misconfiguration, so that
  is now an error.

  Failing before generation means an existing output file is left untouched.

  If an empty schema is a legitimate outcome for your project — everything
  filtered out by `--exclude`, a `--sources` filter that matches nothing, a
  schema mid-migration — pass `--allow-empty` or set `allow_empty = true` under
  `[tool.erdify]`. That restores the previous behavior exactly.

### Added

- New documentation page **Comparison** — erdify next to eralchemy,
  sqlalchemy-schemadisplay, erdantic, `django-extensions graph_models` and
  DBML/dbdiagram, on the axes that actually differ (live connection, importing
  your code, frameworks covered, runtime dependencies, output formats, CI drift
  gate), including where each alternative is the better choice.
- New documentation page **Python Parsing Limitations** — the Python-side
  counterpart to the SQL frontend's "Deferred / Not Supported" table: what the
  AST parser cannot see (runtime-constructed models, non-literal
  `__tablename__`, `__table_args__`, composite foreign keys, foreign keys inside
  `sa_column`, unannotated `relationship()` assignments) and what to do instead.
- New documentation page **Troubleshooting** — symptom-first fixes for models
  not being found, too many entities, missing relationships and missing keys on
  Pydantic/dataclass models.
- Every documentation page now carries its own `description` frontmatter, so
  each page gets its own search-engine snippet and social-card subtitle instead
  of repeating `site_description`.
- `--allow-empty` (and `allow_empty` in `[tool.erdify]`) opts back in to the
  pre-0.13.0 behavior for an empty result: warn, write the empty diagram, exit
  `0`. See the breaking change below.
- erdify now ships `.pre-commit-hooks.yaml`, so it can be used as a pre-commit
  repository instead of a `repo: local` / `language: system` hook that requires
  erdify to be installed in the consumer's environment first. Two ids are
  provided: `erdify` regenerates the diagram (pre-commit fails the commit when
  the file changed), and `erdify-check` never writes and exits non-zero when the
  committed diagram has drifted. `--check` is part of the latter's entry point,
  so overriding `args` cannot drop it. SQL DDL projects add
  `additional_dependencies: ['sqlglot>=25']` rather than using a separate id.
- The documentation site now renders a social card (`og:image`) for every page,
  so links shared on chat, social and link-preview surfaces show a real card
  instead of a bare text entry. This enables mkdocs-material's `social` plugin,
  which pulls in the `mkdocs-material[imaging]` dependencies and their system
  libraries in the docs workflow.
- The changelog is published as a page on the documentation site. It includes
  the repository's `CHANGELOG.md` verbatim via `pymdownx.snippets`, so there is
  still a single source of truth.
- Every documentation page now has an edit link back to its source on GitHub
  (`content.action.edit`; `edit_uri` was already configured but Material never
  rendered the button without the feature) and previous/next navigation in the
  footer (`navigation.footer`).

### Changed

- The "No tables found" message now ends with a link to the troubleshooting
  page, which did not exist when the message was written.

- The Datadog coverage upload is now also skipped for Dependabot. The existing
  fork check covers pull requests from forks, but a Dependabot pull request's
  head branch lives in this repository, and GitHub runs those with Dependabot
  secrets rather than Actions secrets — so the step would have run with an
  empty key and failed the required `Tests passed` check on every dependency
  bump. The condition matches on the actor: secrets cannot be referenced in an
  `if:` conditional, and the documented job-level-env workaround would put the
  API key in the environment of every step in the job.
- `SECURITY.md` scopes its absolute claims to the core install. "Does not
  execute / import / connect / send" holds for the stdlib-only core; the
  `erdify[sql]` extra runs third-party code (sqlglot) in your process and is now
  described as its own trust boundary. Added: `--output`/`--inject` do write to
  the paths you name, and the rendering step (PlantUML server, Mermaid, browser)
  is outside erdify's control. The response times are stated as what a small
  team aims for rather than a service-level guarantee.
- `docs/usage/ci.md` leads with the `--check` drift gate and presents the
  auto-commit workflow as the alternative, with its trade-off stated. The
  workflow examples keep floating action tags for readability, and a note now
  says so explicitly and tells readers to pin to a SHA in their own repository —
  as erdify's own workflows do.
- Reduced decorative emoji in `SECURITY.md` and `CONTRIBUTING.md`, which people
  reach when something is wrong or when they are trying to get set up.
- The "No tables found" warning is now actionable: it names the active
  `--include` patterns, reports how many `.py`/`.sql` files were scanned and how
  many matched, and distinguishes "nothing matched the patterns" (the usual
  cause — `--include` defaults to `models.py`, so models in e.g. `schema.py` are
  never seen) from "files matched but held no recognized models".
- The README now answers "why erdify and not X" right after the feature list,
  with a condensed comparison table and a link to the full one.
- The README shows its example ERD as a live Mermaid diagram injected with
  `erdify --inject` instead of a committed PNG — the format the README itself
  advertises as rendering natively on GitHub. A `readme-erd` pre-commit hook
  runs the same command with `--check`, so the embedded diagram cannot go stale
  (and it dogfoods both flags on the project's own front page).
- The README badge row is down from ten to six: PyPI version, Python versions,
  License, Tests, Coverage and a new docs badge. The Linting, Ruff, mypy and
  download badges added rows without adding information a reader acts on.
- The PyPI project page now links to the documentation site
  (https://erdify.devsuit.io/) instead of the README anchor on GitHub, and
  gains `Changelog` and `Issues` links.
- `[tool.ruff] target-version` is `py311`, matching `requires-python = ">=3.11"`
  instead of contradicting it with `py310`.
- The documentation home page now leads with what erdify is, the
  framework-comparison diagram and a three-line install-and-run, instead of
  restating the sidebar. The `Comparison`, `Python Parsing Limitations` and
  `Troubleshooting` pages are in the nav.
- `docs/frameworks/index.md` loads its second example image from the repository
  instead of `raw.githubusercontent.com`, matching the first one on the page.
- The Mermaid section of `docs/usage/output-formats.md` shows the `.mmd` source
  and the rendered diagram in side-by-side tabs; the rendered-only fence never
  showed readers what the file actually contains.

- The required `Tests passed` check now fails for a pull request from the
  machine-written `badges` branch into `main` (the only base the test workflow
  runs for). GitHub cannot bar a branch from being a pull-request source, and
  such a pull request would otherwise look mergeable while replacing the README
  on `main` with the branch's own.
- Test coverage is now uploaded to Datadog Code Coverage from the Linux /
  Python 3.13 matrix leg, with `code-coverage.datadog.yaml` defining the
  service mapping and 90% total/patch PR gates (matching the existing
  `fail_under`), and `service.datadog.yaml` registering erdify in the Datadog
  Software Catalog. The upload is skipped on pull requests from forks, which
  have no access to repository secrets; the workflow deliberately stays on the
  `pull_request` trigger.
- The README now carries a coverage badge. Datadog exposes no public badge
  endpoint, so pushes to `main` publish the percentage as a shields.io endpoint
  payload on the orphan `badges` branch of this repository, committed by
  `github-actions[bot]` with the workflow's built-in `GITHUB_TOKEN`. Pull
  requests never update it. Keeping the payload in the repository rather than in
  a Gist or a third-party badge service means no personal credential is involved
  and the badge survives any contributor leaving.
- CI now resolves `uv` to `latest-known` instead of `latest`, so the version
  installed in every workflow (including the PyPI publish job) is one whose
  checksum ships with the pinned `setup-uv` release. New `uv` versions reach CI
  only through a `setup-uv` bump, which arrives as a reviewed, cooldown-gated
  Dependabot PR.
- Dependabot's `github-actions` version-update group now includes `major`, so
  major action bumps arrive as a single grouped PR instead of one PR each. The
  `uv` entry deliberately keeps majors separate, and security updates are
  unaffected in both.

## [0.12.3] - 2026-08-24

### Security

- Updated two transitive development dependencies carrying open advisories,
  resolving all six Dependabot alerts (4 high, 2 moderate):
  - `sqlparse` 0.5.5 → 0.6.0 — GHSA-prg7-hcfm-mfcr (ReDoS via dollar-quoted SQL
    literals), GHSA-pwgv-4x5q-6m9f, GHSA-f2ff-p2ww-7p4p, GHSA-3496-9g83-7v6x.
  - `pymdown-extensions` 10.21.3 → 11.0.1 — GHSA-gm37-52c6-37mw,
    GHSA-9xwg-3r6f-jcx2.

  Neither package is a dependency of the published distribution: `erdify`
  declares no runtime dependencies, and both are reached only through the
  development and documentation groups (`sqlparse` via `django`,
  `pymdown-extensions` via `mkdocs-material`). Installations of any previous
  release were therefore never affected; this hardens the development and CI
  toolchain only.

### Changed

- Bumped CI actions to their latest majors (combines Dependabot #142-#145 into
  one change): `astral-sh/setup-uv` 9.0.0 → 10.0.1, `actions/configure-pages`
  5.0.0 → 6.0.0, `actions/upload-pages-artifact` 4.0.0 → 5.0.0, and
  `actions/deploy-pages` 4.0.5 → 5.0.0. The Pages actions move to Node 24;
  `setup-uv` v10 disables its cache by default on `release`/`workflow_run`/
  `pull_request_target` events, which only affects the publish workflow's cache
  hit rate, not its behavior. CI only; no runtime or user-facing change.
- Dependabot now holds freshly published versions back for 7 days
  (`cooldown.default-days: 7` on every `updates` entry) before proposing a
  version update, giving the ecosystem and security researchers time to catch a
  compromised or broken release. Security updates are unaffected — `cooldown`
  applies to version updates only. Repository infrastructure only; no runtime
  or user-facing change.

## [0.12.2] - 2026-08-19

### Changed

- Bumped development dependencies (`version-updates` group): `sqlglot`
  (30.15.0 → 30.17.0), `ruff` (0.16.2 → 0.16.3), `mypy` (2.3.0 → 2.3.1), and
  `sqlalchemy` (2.0.51 → 2.0.52). No runtime or user-facing change; the core
  install stays dependency-free.
- The documentation site is now deployed through the GitHub Pages Actions
  workflow (upload-pages-artifact/deploy-pages) instead of pushing to the
  `gh-pages` branch, which the "Protect GH Pages" ruleset blocks. Repository
  infrastructure only — the published site is unchanged.

## [0.12.1] - 2026-08-12

### Changed

- Bumped development dependencies: `ruff` (0.16.0 → 0.16.2), `sqlglot`
  (30.14.0 → 30.15.0), and `django` (5.2.16 → 5.2.17). No runtime or
  user-facing change; the core install stays dependency-free.

## [0.12.0] - 2026-08-03

### Added

- SQL frontend: a single-column `UNIQUE` foreign key is now rendered as a **1:1**
  relationship instead of N:1 — `|o--||` when the column is `NOT NULL`, `|o--o|`
  when it is nullable (the child end is `|o`, since a `UNIQUE` FK caps a parent
  at zero-or-one child). Both column-level `UNIQUE` and single-column table-level
  `UNIQUE (col)` (anonymous or named `CONSTRAINT ... UNIQUE (col)`) are
  recognized; composite `UNIQUE (a, b)` is out of scope. A unique non-primary-key
  column is also marked `UK` in the entity block, and the `--format json` output
  gains a `unique` boolean per field. Other frontends are unaffected (#97).

## [0.11.5] - 2026-07-29

### Changed

- Bumped development dependencies (`version-updates` group): `sqlglot`
  (30.13.0 → 30.14.0) and `ruff` (0.15.22 → 0.16.0); relaxed the `uv-build`
  build requirement to `>=0.11.19,<0.13.0`. No runtime or user-facing change;
  the core install stays dependency-free.
- Pinned the ruff rule set (`[tool.ruff.lint] select = ["E", "F"]`) so the
  ruff 0.16.0 default-rule expansion (59 → 413 rules) stays behavior-neutral;
  adopting the new rules is tracked separately.

## [0.11.4] - 2026-07-23

### Fixed

- Structural link-table detection now recognizes composite-PK association
  tables with more than two foreign keys (ternary and higher-order joins), not
  just two-FK tables. A table whose primary key is made up entirely of foreign
  keys — with no payload columns — is flagged as a link table regardless of its
  name or arity, and higher-order ones are drawn as a star of edges from each
  parent to the link entity. The rule is shared by every parser backend (Python
  AST, Core `Table(...)` synthesis, and the SQL DDL frontend), so it can no
  longer drift between them (#118).

## [0.11.3] - 2026-07-21

### Changed

- Bumped development dependencies (`version-updates` group): `ast-serialize`,
  `librt`, `mkdocs-material`, `mypy`, `ruff`, `sqlglot`, and `django`
  (5.2.15 → 5.2.16). No runtime or user-facing change; the core install stays
  dependency-free.

## [0.11.2] - 2026-07-01

### Changed

- Bumped CI actions: `actions/setup-python` 6.2.0 → 6.3.0,
  `astral-sh/setup-uv` 7.6.0 → 8.2.0, `actions/checkout` 6.0.3 → 7.0.0.
- Bumped development dependencies (`version-updates` group): `sqlglot`,
  `ruff`, `sqlmodel`.

## [0.11.1] - 2026-06-24

### Changed

- Documentation: expanded SQL DDL frontend coverage across quickstart, CLI, CI,
  filtering and frameworks pages; added a pepy.tech download badge to the README.
- Bumped development dependencies (`version-updates` group).

## [0.11.0] - 2026-06-19

### Added

- SQL DDL frontend via the optional `erdify[sql]` extra (sqlglot): generate an
  ERD from `.sql` files (`CREATE TABLE`, inline/table/`ALTER TABLE` foreign
  keys, `NOT NULL`/`DEFAULT`, `CREATE TYPE ... AS ENUM`, `CREATE INDEX`) with
  no database connection. New `--sql-dialect` flag / `sql_dialect` config key;
  `input` now accepts a file as well as a directory. Core install stays
  dependency-free.

## [0.10.0] - 2026-06-17

### Added

- `--inject FILE` — write the diagram into a markdown file between
  `<!-- erdify:start -->` / `<!-- erdify:end -->` markers, so it renders natively
  on GitHub/GitLab. Only the marked region is rewritten; the rest of the file is
  preserved. Uses a single `--format` (default `mermaid`); combine with `--check`
  to fail on drift in CI. Also settable as `inject` in `[tool.erdify]`.

## [0.9.0] - 2026-06-17

### Added

- `--include` — scan model files beyond `models.py` via glob patterns (e.g.
  `--include '**/models/*.py' tables.py`). Patterns with `/` match the path
  relative to the input (`**` crosses directories); patterns without `/` match a
  filename at any depth. `--include` replaces the default `models.py`, and is
  also settable as `include` in `[tool.erdify]`. When run at the default, erdify
  now hints (once, on stderr) about a `models/` package it skipped.

## [0.8.0] - 2026-06-17

> **⚠️ Heads-up — your committed ERDs will reorder once after upgrading.**
> Model files are now discovered in **sorted** order, so the elements in the
> generated `.puml` / `.mmd` output appear in a new, deterministic order. The
> **diagram content is unchanged** — identical entities, columns and
> relationships — only their ordering differs. Expect a **one-time diff** the
> next time erdify regenerates (e.g. in a pre-commit hook or CI `--check`);
> commit it once and output is stable across machines thereafter.

### Changed

- The `models.py` scan now prunes excluded directories (venv/site-packages/
  caches) **during** the directory walk instead of filtering them out after a
  full `rglob`. Large non-project trees like `.venv` are no longer traversed,
  cutting scan time substantially on real repos (e.g. ~6800 → ~120 directories
  walked, ~3.5× faster end-to-end on a repo with erdify running from its root).
- Discovered model files are now sorted, so the generated ERD has a
  deterministic, machine-independent element order. Existing diagrams may show a
  one-time reordering diff on regeneration; output is stable thereafter.

## [0.7.2] - 2026-06-16

### Changed

- Refined the PyPI project summary to "A zero-dependency ERD generator for your
  Python models — pure AST, no database required." No code changes — this release
  refreshes the published project metadata.

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

[Unreleased]: https://github.com/devsuit-berlin/erdify/compare/v0.14.1...HEAD
[0.14.1]: https://github.com/devsuit-berlin/erdify/compare/v0.14.0...v0.14.1
[0.14.0]: https://github.com/devsuit-berlin/erdify/compare/v0.13.0...v0.14.0
[0.13.0]: https://github.com/devsuit-berlin/erdify/compare/v0.12.3...v0.13.0
[0.12.3]: https://github.com/devsuit-berlin/erdify/compare/v0.12.2...v0.12.3
[0.12.2]: https://github.com/devsuit-berlin/erdify/compare/v0.12.1...v0.12.2
[0.12.1]: https://github.com/devsuit-berlin/erdify/compare/v0.12.0...v0.12.1
[0.12.0]: https://github.com/devsuit-berlin/erdify/compare/v0.11.5...v0.12.0
[0.11.5]: https://github.com/devsuit-berlin/erdify/compare/v0.11.4...v0.11.5
[0.11.4]: https://github.com/devsuit-berlin/erdify/compare/v0.11.3...v0.11.4
[0.11.3]: https://github.com/devsuit-berlin/erdify/compare/v0.11.2...v0.11.3
[0.11.2]: https://github.com/devsuit-berlin/erdify/compare/v0.11.1...v0.11.2
[0.11.1]: https://github.com/devsuit-berlin/erdify/compare/v0.11.0...v0.11.1
[0.11.0]: https://github.com/devsuit-berlin/erdify/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/devsuit-berlin/erdify/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/devsuit-berlin/erdify/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/devsuit-berlin/erdify/compare/v0.7.2...v0.8.0
[0.7.2]: https://github.com/devsuit-berlin/erdify/compare/v0.7.1...v0.7.2
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
