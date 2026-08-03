# SQL DDL Frontend

erdify can generate an ERD directly from `.sql` files — no database connection, no
ORM models required. The SQL frontend is an **optional extra** that pulls in
[sqlglot](https://github.com/tobymao/sqlglot) as the only additional dependency.

## Installation

```bash
pip install "erdify[sql]"
# or with uv
uv add "erdify[sql]"
```

The core `erdify` package remains dependency-free; sqlglot is only installed when
you request the `[sql]` extra.

## Usage

Point erdify at a single `.sql` file, or at a directory together with
`--include '*.sql'` to discover `.sql` files recursively. Passing a directory
**without** `--include` uses the default `models.py` pattern and will not pick
up any `.sql` files.

```bash
# Single file — no --include needed
erdify schema.sql

# Directory — must add --include to discover .sql files
erdify ./db/migrations --include '*.sql'

# Deeper trees use the same pattern
erdify ./db --include '*.sql'

# Specify the SQL dialect explicitly
erdify schema.sql --sql-dialect postgres
```

### `--sql-dialect`

erdify passes the dialect to sqlglot's parser. Omitting it uses sqlglot's generic
dialect, which handles standard SQL well but silently drops dialect-specific
constructs. Notable case:

- **`CREATE TYPE ... AS ENUM`** is a PostgreSQL extension. It is only recognised
  when you pass `--sql-dialect postgres`. Under the generic dialect those statements
  are skipped and no enum entities are emitted.

The flag is also settable in `pyproject.toml`:

```toml
[tool.erdify]
sql_dialect = "postgres"
```

## Supported DDL Subset

| Construct | Support | Notes |
|-----------|---------|-------|
| `CREATE TABLE` | ✅ | Table name becomes the entity name; schema-qualified names (`schema.table`) are normalised to the table name part |
| Primary keys — inline (`col INT PRIMARY KEY`) | ✅ | |
| Primary keys — table constraint (`PRIMARY KEY (col, …)`) | ✅ | Composite PKs supported |
| Foreign keys — inline (`col INT REFERENCES other(id)`) | ✅ | |
| Foreign keys — table constraint (`FOREIGN KEY … REFERENCES …`) | ✅ | |
| Foreign keys — `ALTER TABLE … ADD FOREIGN KEY` | ✅ | Two-pass resolution; forward references resolved after all tables are parsed |
| `NOT NULL` | ✅ | Reflected in the `nullable` field attribute |
| `DEFAULT` | ✅ | Default expression captured as a string |
| `CREATE TYPE … AS ENUM` | ✅ | Requires `--sql-dialect postgres`; silently skipped under the generic dialect |
| `CREATE INDEX` | ✅ (JSON only) | Detected and emitted in `--format json`; not drawn in PlantUML or Mermaid diagrams (consistent with the Indexes note in the [feature matrix](../features.md)) |

> **NOTE:** Functional/expression indexes (e.g. `CREATE INDEX ... ON t(lower(col))`) are not mapped
> to a column — only plain-column indexes set the JSON `index` flag. Expression indexes are silently
> ignored.

## Relationship Cardinality

A foreign key is rendered as **N:1** (`}o--||`) by default. A single-column
`UNIQUE` foreign key is a **1:1** relationship, drawn `child ... parent`: the
child end is `|o` (uniqueness caps a parent at zero-or-one child), and the
parent end follows FK nullability — so it renders `|o--||` when the column is
`NOT NULL`, and `|o--o|` when it is nullable. Both
column-level `col ... UNIQUE` and single-column table-level `UNIQUE (col)`
(anonymous or named `CONSTRAINT ... UNIQUE (col)`) are recognized; composite
`UNIQUE (a, b)` is not. A unique non-primary-key column is also flagged with a
`UK` marker in the entity block ([#97](https://github.com/devsuit-berlin/erdify/issues/97)).

## Deferred / Not Supported

The following constructs are intentionally out of scope for v1:

| Item | Status |
|------|--------|
| Composite `UNIQUE (a, b)` → relationship | Not supported (single-column only) |
| `CREATE VIEW` | Not supported |
| `CHECK` constraints | Not supported |
| Triggers / stored procedures | Not supported |
| Live database introspection | Not supported (no connection required by design) |

## Example

```sql
-- schema.sql (PostgreSQL)
CREATE TYPE user_role AS ENUM ('admin', 'member', 'guest');

CREATE TABLE users (
    id   SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    role user_role NOT NULL DEFAULT 'member'
);

CREATE TABLE orders (
    id         SERIAL PRIMARY KEY,
    user_id    INT NOT NULL REFERENCES users(id),
    total      NUMERIC(10, 2) NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
```

```bash
erdify schema.sql --sql-dialect postgres --format mermaid
```

produces a Mermaid ERD with `users`, `orders` and the `user_role` enum, with a
foreign-key edge from `orders.user_id` to `users`.
