# Quickstart

Already [installed erdify](installation.md)? These are the commands you'll reach
for most. Each links to the page with the full details.

## Generate your first diagram

Point erdify at a directory; it finds `models.py` files recursively and prints a
PlantUML ERD to stdout:

```bash
erdify ./src
```

Write it to a file instead:

```bash
erdify ./src -o docs/erd.puml
```

No installation? Run it on demand with [uvx](installation.md#using-uvx-no-installation-needed):

```bash
uvx erdify ./src -o erd.puml
```

## Common recipes

```bash
# PlantUML and Mermaid in one run
erdify ./src -o docs/erd --format plantuml mermaid

# Only database-backed models (skip Pydantic/dataclass)
erdify ./src --sources sqlmodel sqlalchemy

# Drop noisy tables and skip migration folders
erdify ./src --exclude '*Link' audit_log --exclude-paths migrations

# Fail CI if the committed diagram is out of date
erdify ./src -o docs/erd.puml --check
```

| Want to… | See |
| --- | --- |
| Choose PlantUML / Mermaid / JSON / HTML | [Output Formats](usage/output-formats.md) |
| Exclude entities, paths, or model kinds | [Filtering & Key Inference](usage/filtering.md) |
| Commit flags instead of typing them | [`[tool.erdify]` config](usage/cli.md#configuration-via-pyprojecttoml) |
| Render the diagram to an image | [Viewing the Diagram](usage/viewing.md) |
| Keep the ERD fresh in CI / pre-commit | [CI/CD & pre-commit](usage/ci.md) |
| Generate diagrams from Python | [Python API](usage/cli.md#python-api) |

## Next steps

- Browse every flag in the [CLI reference](usage/cli.md).
- See a worked example per framework in the [Frameworks overview](frameworks/index.md).
