# CLI & Python API

erdify ships a command-line interface, a module entry point, and a Python API for programmatic use.

## CLI Options

```bash
usage: erdify [-h] [-o OUTPUT] [--title TITLE] [--exclude [PATTERN ...]]
                    [--exclude-paths [PATTERN ...]] [--no-default-excludes]
                    [--sources [KIND ...]] [--infer-keys] [--django-raw-types]
                    [--no-enums] [--no-relationships] [--check] [-v]
                    input

Generate PlantUML ERD diagrams from SQLModel, SQLAlchemy, Django, Pydantic and dataclass models

positional arguments:
  input                 Directory containing model files (searches for models.py recursively)

options:
  -h, --help            show this help message and exit
  -o OUTPUT, --output OUTPUT
                        Output .puml file (default: stdout)
  --title TITLE         Diagram title (default: 'Database ERD')
  --exclude [PATTERN ...]
                        Glob patterns (case-sensitive) to exclude entities by
                        class name or table name, e.g. --exclude '*Link' audit_log
  --exclude-paths [PATTERN ...]
                        Glob patterns for models.py files to skip before parsing,
                        matched against the path relative to input or any path
                        segment, e.g. --exclude-paths migrations legacy
  --no-default-excludes
                        Do not auto-skip models.py under venv/site-packages/cache
                        dirs (.venv, site-packages, __pycache__, ...); scan them too
  --sources [KIND ...]  Restrict which model kinds become entities. Choices:
                        sqlmodel, sqlalchemy, django, dataclass, pydantic.
                        Default: all, e.g. --sources sqlmodel sqlalchemy for DB
                        tables only
  --infer-keys          For keyless models (Pydantic/dataclass), infer a primary
                        key from a field named 'id' and a foreign key from '<x>_id'
  --django-raw-types    For Django models, show original field names (CharField,
                        TextField) instead of mapped Python types (str, int)
  --no-enums            Skip enum definitions in output
  --no-relationships    Skip relationship lines in output
  --format FMT [FMT ...]
                        Output format(s): plantuml (.puml), mermaid (.mmd),
                        json (.json), html (.html). Default: plantuml.
                        See Output Formats.
  --check               Don't write; exit non-zero if the --output file is
                        missing or differs from the freshly generated diagram
  -v, --version         show program's version number and exit
```

## Configuration via `pyproject.toml`

Instead of passing flags every time, commit them under `[tool.erdify]` in your
project's `pyproject.toml`. erdify searches upward from the input directory for
the nearest `pyproject.toml` and reads that table.

```toml
[tool.erdify]
title = "My Database Schema"
output = "docs/database_erd"        # relative paths resolve from the project root
format = ["plantuml", "mermaid"]    # one or both
sources = ["django"]
exclude = ["audit_log", "*Link"]
exclude_paths = ["migrations", "legacy"]
infer_keys = true
django_raw_types = false
```

With that in place, `erdify .` uses these settings. Precedence is **explicit CLI
flag > `[tool.erdify]` value > built-in default**. (Boolean flags merge by OR: a
flag enabled in config can be added to on the CLI but not turned off there.)

## Keeping the diagram in sync (`--check`)

`--check` regenerates the diagram in memory and compares it to the existing
`--output` file without writing. It exits `0` when they match and non-zero when
the file is missing or stale — ideal for CI or a pre-commit hook.

```bash
erdify ./src/database -o docs/erd.puml --check
```

## Running as Module

```bash
python -m erdify ./src/database -o erd.puml
```

## Python API

```python
from pathlib import Path
from erdify import parse_models_directory, generate_plantuml

# Parse your models
entities, enums = parse_models_directory(Path("./src/database"))

# Generate PlantUML
diagram = generate_plantuml(
    entities=entities,
    enums=enums,
    title="My Database ERD"
)

# Save or use the diagram
Path("erd.puml").write_text(diagram)
```

## Programmatic Access

For lower-level control, use the parser and generator classes directly:

```python
from erdify import (
    ASTDatabaseParser,
    PlantUMLGenerator,
    EntityInfo,
    FieldInfo,
    EnumInfo,
)

# Low-level parser access
parser = ASTDatabaseParser(Path("./models"))
entities, enums = parser.parse_all_models()

# Access entity details
for name, entity in entities.items():
    print(f"Table: {entity.table_name}")
    for field in entity.fields:
        if field.is_primary_key:
            print(f"  PK: {field.name}")
        elif field.is_foreign_key:
            print(f"  FK: {field.name} -> {field.foreign_table}")

# Custom generator with options
generator = PlantUMLGenerator(
    entities=entities,
    enums=enums,
    title="Custom ERD"
)
output = generator.generate()
```
