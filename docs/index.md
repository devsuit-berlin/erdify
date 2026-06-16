# erdify Documentation

**erdify** parses your model files using AST (Abstract Syntax Tree) and generates comprehensive ERD diagrams in PlantUML format. It supports SQLModel, SQLAlchemy 2.0, Django ORM, Pydantic and standard-library dataclasses — no database connection required. This documentation covers installation, usage, framework support and viewing the generated diagrams.

## Contents

- [Installation](installation.md) — install via pip, uv, pipx or run with uvx
- [Quickstart](quickstart.md) — the handful of commands you'll use most, with links to the details
- [CLI & Python API](usage/cli.md) — command-line options, running as a module, and the Python API (incl. programmatic access)
- [Output Formats](usage/output-formats.md) — PlantUML and Mermaid, `--format`, output naming
- [Filtering & Key Inference](usage/filtering.md) — `--exclude`, `--exclude-paths`, `--sources`, and `--infer-keys`
- [Viewing the Diagram](usage/viewing.md) — render online, locally with PlantUML, or in VS Code
- [CI/CD & pre-commit](usage/ci.md) — keep ERDs up to date in CI and via pre-commit hooks
- [Frameworks Overview](frameworks/index.md) — the five frameworks side by side, how each is detected, and a worked example with the generated PlantUML
- [Django ORM](frameworks/django.md) — Django-specific parsing details (FK mapping, type mapping, enums, abstract bases, `db_table`)
