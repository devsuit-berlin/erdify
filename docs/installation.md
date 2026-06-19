# Installation

erdify can be installed with your Python package manager of choice, or run on demand without installing.

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
