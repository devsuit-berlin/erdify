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
follows these versions, and CI tests each of them. For SQLModel, SQLAlchemy and
Django, CI checks erdify's output against the schema the real framework builds
(the ground-truth tests). "Current release" is the version in erdify's
lockfile, which Dependabot keeps up to date.

| Framework | Supported | Checked in CI |
|---|---|---|
| SQLModel | 0.0.22 and later | 0.0.22 (the oldest) and the current release |
| SQLAlchemy | 2.0, 2.1 (the annotated `Mapped[...]` style) | newest patch release of 2.0 and of 2.1 |
| Django | 5.2, 6.0, 6.1 | newest patch release of each series |
| Pydantic | 2 | the current release (fixtures import; ground-truth tests are planned, [#267](https://github.com/devsuit-berlin/erdify/issues/267)) |
| dataclasses | the standard library of each supported Python | every supported Python |
| SQL DDL (`erdify[sql]`) | sqlglot 25 and later | the current sqlglot release (ground-truth tests are planned, [#266](https://github.com/devsuit-berlin/erdify/issues/266)) |

Where a framework changed what it builds in a release, erdify's diagram is
checked against both sides of that release. Known gaps are listed under
[Limitations](frameworks/limitations.md) and in the issue tracker, for example
SQLModel 0.0.32+ applying `Field()` settings given in `Annotated[...]`
metadata, which erdify doesn't read yet
([#295](https://github.com/devsuit-berlin/erdify/issues/295)).

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
