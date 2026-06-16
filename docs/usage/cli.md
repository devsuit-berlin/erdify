# CLI & Python API

erdify ships a command-line interface, a module entry point, and a Python API for programmatic use.

## CLI Options

```bash
usage: erdify [-h] [-o OUTPUT] [--title TITLE] [--exclude [PATTERN ...]]
                    [--exclude-paths [PATTERN ...]] [--no-default-excludes]
                    [--sources [KIND ...]] [--infer-keys] [--django-raw-types]
                    [--no-enums] [--no-relationships] [-v]
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
  -v, --version         show program's version number and exit
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
