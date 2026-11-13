---
description: "Generate an ERD from .sql DDL files with the optional erdify[sql] extra: CREATE TABLE, foreign keys, enums and dialect handling."
---

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
| `CREATE TABLE` | ✅ | Table name becomes the entity name; schema-qualified names (`schema.table`) are normalised to the table name part. Trailing table options sqlglot doesn't know (SQLite's `WITHOUT ROWID`) are ignored |
| Primary keys — inline (`col INT PRIMARY KEY`) | ✅ | |
| Primary keys — table constraint (`PRIMARY KEY (col, …)`) | ✅ | Composite PKs supported |
| Foreign keys — inline (`col INT REFERENCES other(id)`) | ✅ | Without a column list (`REFERENCES other`), the key references `other`'s primary key, paired in key order for a composite key |
| Foreign keys — table constraint (`FOREIGN KEY … REFERENCES …`) | ✅ | |
| Foreign keys — `ALTER TABLE … ADD FOREIGN KEY` | ✅ | Two-pass resolution; forward references resolved after all tables are parsed |
| `NOT NULL` / `NULL` | ✅ | Reflected in the `nullable` field attribute; an explicit `NULL` (or no constraint) is nullable. A primary-key column is always treated as `NOT NULL` (SQL standard), including under `--sql-dialect sqlite`, where a non-`INTEGER` or composite key of a rowid table technically accepts `NULL` (a legacy quirk SQLite documents as a bug) |
| `DEFAULT` | ✅ | Default expression captured as a string |
| `CREATE TYPE … AS ENUM` | ✅ | Requires `--sql-dialect postgres`; silently skipped under the generic dialect |
| `CREATE INDEX` | ✅ (JSON only) | Detected and emitted in `--format json`; not drawn in PlantUML or Mermaid diagrams (consistent with the Indexes note in the [feature matrix](../features.md)) |
| `CREATE UNIQUE INDEX` | ✅ | On one plain column and without `WHERE`, the column is unique like a `UNIQUE` constraint (`UK`, 1:1 for a foreign key). A composite, partial or expression unique index doesn't make a column unique |
| Identifier case | ✅ | Names are resolved the way the dialect folds them: unquoted names are case-insensitive (`REFERENCES Customer(ID)` is `customer.id`), and with `--sql-dialect postgres` a quoted `"Account"` stays apart from `account`. A name that still matches nothing exactly is matched case-insensitively when that is unambiguous |
| Quoted names with spaces or punctuation (`"Order Items"`) | ✅ | Kept in the IR and JSON; each diagram format encodes what its syntax can't take ([Names with spaces or special characters](../usage/output-formats.md#names-with-spaces-or-special-characters)) |

> **NOTE:** Functional/expression indexes (e.g. `CREATE INDEX ... ON t(lower(col))`) are not mapped
> to a column — only plain-column indexes set the JSON `index` flag. Expression indexes are silently
> ignored.

## Relationship Cardinality

A foreign key is rendered as **N:1**: `}o--||` when the column is `NOT NULL`,
and `}o--o|` when it is nullable. A single-column
`UNIQUE` foreign key is a **1:1** relationship, drawn `child ... parent`: the
child end is `|o` (uniqueness caps a parent at zero-or-one child), and the
parent end follows FK nullability — so it renders `|o--||` when the column is
`NOT NULL`, and `|o--o|` when it is nullable. Both
column-level `col ... UNIQUE` and single-column table-level `UNIQUE (col)`
(anonymous or named `CONSTRAINT ... UNIQUE (col)`) and a single-column
`CREATE UNIQUE INDEX` are recognized; composite `UNIQUE (a, b)` is not. A unique non-primary-key column is also flagged with a
`UK` marker in the entity block ([#97](https://github.com/devsuit-berlin/erdify/issues/97)).
A foreign key that is also the table's only primary-key column (a shared
primary key, e.g. `id INTEGER PRIMARY KEY REFERENCES users(id)`) is unique by
definition and is drawn 1:1 as well; one that is part of a composite primary
key stays N:1.

A statement that fails to parse is reported on stderr and skipped; the rest of
its file is still read (with [`--strict`](../usage/cli.md#files-that-cannot-be-parsed-strict),
erdify exits `1` instead).

erdify's reading of DDL is checked against the schema SQLite builds from the
same statements (tables, keys, nullability, uniqueness) by the
[ground-truth tests](https://github.com/devsuit-berlin/erdify/blob/main/CONTRIBUTING.md#ground-truth-tests).

## Deferred / Not Supported

The following constructs are intentionally out of scope for v1:

| Item | Status |
|------|--------|
| Composite `UNIQUE (a, b)` → relationship | Not supported (single-column only) |
| `CREATE VIEW` | Not supported |
| `CREATE VIRTUAL TABLE` (SQLite FTS, R*Tree, …) | Not supported (skipped) |
| `CHECK` constraints | Not supported |
| Generated columns with `STORED` / `VIRTUAL` without `--sql-dialect` | sqlglot's generic dialect can't parse them: that `CREATE TABLE` is skipped with a parse error. Pass `--sql-dialect` (e.g. `postgres`, `mysql`, `sqlite`) |
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
