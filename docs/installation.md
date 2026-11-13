---
description: "Install erdify with pip, uv, pipx or uvx, add the optional [sql] extra, and check the supported Python versions."
---

# Installation

erdify can be installed with your Python package manager of choice, or run on demand without installing.

## Requirements

erdify supports **Python 3.11 – 3.15** and has no runtime dependencies. Every
supported version is tested in CI on Linux; the oldest and newest are also
tested on macOS and Windows.

## Supported framework versions

erdify reads model files as text and never imports them, so your project's
framework doesn't need to be installed alongside erdify. The version still
matters: it decides which syntax exists and what schema the framework builds
from it (default table names, which settings a column takes, and so on). erdify
follows these versions; CI runs the ones in the "Checked in CI" column. For
SQLModel, SQLAlchemy, Django, Pydantic, dataclasses and SQL DDL, it checks erdify's output against the schema
the real framework (for SQL DDL: SQLite; for Pydantic and dataclasses: the classes' own fields) builds (the ground-truth tests). "Current release" is the version in erdify's
lockfile, which Dependabot keeps up to date.

| Framework | Supported | Checked in CI |
|---|---|---|
| SQLModel | 0.0.22 and later | 0.0.22 (the oldest), 0.0.32 (see below) and the current release |
| SQLAlchemy | 2.0, 2.1 (the annotated `Mapped[...]` style) | newest patch release of 2.0 and of 2.1 |
| Django | 5.2, 6.0, 6.1 | newest patch release of each series |
| Pydantic | 2 | the current release |
| dataclasses | the standard library of each supported Python | every supported Python |
| SQL DDL (`erdify[sql]`) | sqlglot 30.8 and later | 30.8 (the oldest), 30.17 (see below) and the current release |

Where a framework changed what it builds in a release, erdify's diagram is
checked against both sides of that release, and that release is itself a CI
leg.
For sqlglot, that is 30.17, the first release that parses SQLite's short
generated-column form (`col TEXT AS (expr)` with `--sql-dialect sqlite`);
with an older sqlglot, a table that uses it is skipped with a parse error.

The newest releases are also tested every week by a scheduled workflow, without
waiting for the lockfile: the whole test suite runs on the newest SQLModel,
Pydantic, sqlglot and Django releases and the newest SQLAlchemy they accept,
and a Django or SQLAlchemy series that is out but missing from the CI matrix is
reported. Known gaps are listed under
[Limitations](frameworks/limitations.md) and in the issue tracker, for example
settings inside SQLModel's `Field(sa_column=Column(...))`, which erdify doesn't
read yet ([#309](https://github.com/devsuit-berlin/erdify/issues/309)).

## Using pip

```bash
pip install erdify
```

## Using uv

```bash
uv add erdify
```

## Using pipx (recommended for CLI usage)

```bash
pipx install erdify
```

## Using uvx (no installation needed)

```bash
# Run directly without installing
uvx erdify ./src/database -o erd.puml
```

## SQL support (optional)

Parsing SQL DDL (`.sql`) files requires the `sql` extra, which pulls in
[sqlglot](https://github.com/tobymao/sqlglot). The core install stays
dependency-free; only this extra adds a runtime dependency.

```bash
pip install 'erdify[sql]'
# or: uv add 'erdify[sql]'
# or: pipx install 'erdify[sql]'

# Run on demand without installing:
uvx --from 'erdify[sql]' erdify schema.sql
```

See [SQL DDL](frameworks/sql.md) for usage and the supported statements.
