# Filtering & Key Inference

Control which entities and model kinds appear in the diagram, and derive keys for keyless models.

## Choosing Which Files Are Scanned (`--include`)

By default erdify scans every file named `models.py` (at any depth). To scan
other files — a `models/` package, or files like `tables.py`/`db.py` — pass
`--include` with one or more glob patterns:

```bash
# A models/ package split across files
erdify ./app --include '**/models/*.py'

# Keep models.py AND add a package and a custom file
erdify ./app --include models.py '**/models/*.py' tables.py
```

Pattern rules:

- A pattern **with `/`** (e.g. `**/models/*.py`, `app/db.py`) matches the path
  relative to the input. `**` crosses directories; `*` and `?` do not cross `/`.
- A pattern **without `/`** (e.g. `models.py`, `*_models.py`) matches a
  **filename at any depth**.

`--include` **replaces** the default, so include `models.py` explicitly if you
still want it. Equivalent `[tool.erdify]` config:

```toml
[tool.erdify]
include = ["models.py", "**/models/*.py"]
```

If erdify sees a `models/` package while running with the default, it prints a
one-line hint suggesting `--include '**/models/*.py'`.

!!! tip "Prefer targeted patterns over `**/*.py`"
    Point `--include` at where your models actually live (`**/models/*.py`,
    `tables.py`, `*_models.py`) rather than scanning every Python file with
    `**/*.py`. A repo-wide scan also reads unrelated modules — and if a
    non-model class happens to share a name with one of your models (e.g. a
    `Paragraph` helper in a test file and a `Paragraph` model), the last file
    parsed wins, so a model can be shadowed and dropped from the diagram.
    Narrow patterns keep the scan fast and unambiguous.

## Excluding Entities

Use `--exclude` to drop tables/entities from the diagram. Each pattern is a
case-sensitive [glob](https://docs.python.org/3/library/fnmatch.html) tested
against both the **class name** and the **table name** — an entity is excluded
if either matches. Any relationships pointing at an excluded entity are dropped
too, so no dangling lines remain.

```bash
# Exclude all link tables (class names ending in "Link")
erdify ./src/database --exclude '*Link'

# Exclude by table name, with multiple patterns
erdify ./src/database --exclude audit_log 'tmp_*' Session
```

> 💡 Quote patterns containing `*` so your shell doesn't expand them.

## Excluding by Path (`--exclude-paths`)

`--exclude` filters by name **after** parsing. To skip whole folders **before**
the scan — e.g. so erdify never reads a virtualenv's third-party `models.py` —
use `--exclude-paths`. Patterns are case-sensitive globs matched against each
scanned file's path relative to the input **or** any single path segment (it
applies to every discovered file, including extra ones added via `--include`).

```bash
# Skip migrations and a legacy app, anywhere in the tree
erdify ./backend --exclude-paths migrations legacy

# Precise path glob
erdify ./backend --exclude-paths 'apps/experimental/*'
```

By default erdify already auto-skips `models.py` under common non-project
directories — `site-packages`, `.venv`, `venv`, `env`, `virtualenv`,
`node_modules`, `__pycache__`, `.git`, `.tox`, `.mypy_cache`, `.pytest_cache` —
so running on a Django project picks up only your own apps, not installed
packages like `django.contrib.*`, `constance` or `django_celery_beat`. Pass
`--no-default-excludes` to scan those directories too.

## Filtering by Model Kind

Use `--sources` to restrict the diagram to specific model frameworks. By default
all recognized kinds are drawn (`sqlmodel`, `sqlalchemy`, `django`, `dataclass`,
`pydantic`). This is the precise alternative to `--exclude` when you want a pure
DB-table ERD and don't want Pydantic DTOs or `@dataclass` query wrappers to leak in.

```bash
# Only real DB tables — drops Pydantic/dataclass models entirely
erdify ./src/database --sources sqlmodel sqlalchemy

# ORM tables plus your Pydantic schemas, but no dataclasses
erdify ./src/database --sources sqlmodel pydantic
```

> 💡 `--sources` filters by *kind*; `--exclude` filters by *name*. Combine them freely.

## Inferring keys (`--infer-keys`)

Pydantic models and dataclasses have **no database key concept**. By default all
fields are rendered as plain columns and relationships come only from nested
model references. If your models follow a database-like naming convention, pass
`--infer-keys` to derive keys from field names:

- a field named **`id`** → **primary key**
- a field named **`<x>_id`** → **foreign key** targeting table **`<x>`**

```bash
# Plain columns (default)
erdify ./src/schemas

# Infer PK/FK from id / <x>_id naming
erdify ./src/schemas --infer-keys
```

> ℹ️ `--infer-keys` only affects Pydantic/dataclass models. SQLModel and
> SQLAlchemy keys are always read from the explicit definitions and never
> overridden.
