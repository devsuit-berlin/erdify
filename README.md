# 🗃️ erdify

[![PyPI version](https://img.shields.io/pypi/v/erdify)](https://pypi.org/project/erdify/)
[![Python versions](https://img.shields.io/pypi/pyversions/erdify)](https://pypi.org/project/erdify/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://github.com/devsuit-berlin/erdify/actions/workflows/test.yml/badge.svg)](https://github.com/devsuit-berlin/erdify/actions/workflows/test.yml)
[![Linting](https://github.com/devsuit-berlin/erdify/actions/workflows/lint.yml/badge.svg)](https://github.com/devsuit-berlin/erdify/actions/workflows/lint.yml)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Checked with mypy](https://img.shields.io/badge/mypy-checked-blue)](https://mypy-lang.org/)

> 🚀 Generate beautiful PlantUML Entity Relationship Diagrams from your SQLModel, SQLAlchemy, Django, Pydantic and dataclass models automatically!

**erdify** parses your model files using AST (Abstract Syntax Tree) and generates comprehensive ERD diagrams in PlantUML format. It supports SQLModel, SQLAlchemy 2.0, Django ORM, Pydantic and standard-library dataclasses. No database connection required!

## ✨ Features

- 📊 **Automatic ERD Generation** - Parse your models and generate PlantUML diagrams
- 🧬 **5 Frameworks** - SQLModel, SQLAlchemy 2.0, Django ORM, Pydantic and dataclasses
- 🔍 **AST-Based Parsing** - No imports needed, works with any valid Python code
- 🎯 **Zero Runtime Dependencies** - Uses only Python standard library
- 🔗 **Relationship Detection** - Automatically detects foreign keys and relationships
- 🔑 **Key Inference** - `--infer-keys` derives PK/FK from field names for keyless models
- 🚫 **Exclude Patterns** - Filter out entities by class or table name with glob patterns
- 🎚️ **Source Filtering** - Restrict the diagram to specific model kinds with `--sources`
- ⚙️ **Config File** - Commit options under `[tool.erdify]` in `pyproject.toml`
- ✅ **Drift Check** - `--check` fails CI/pre-commit when the committed diagram is stale
- 📦 **Inheritance Support** - Resolves fields from base classes and mixins
- 🏷️ **Enum Support** - Includes enum definitions in the diagram
- 🔄 **Link Table Detection** - Identifies many-to-many association tables structurally
- 🧜 **PlantUML & Mermaid** - `--format` outputs PlantUML and/or Mermaid (renders natively on GitHub)
- 🎨 **Beautiful Output** - Clean, readable diagrams with proper styling

## 🚀 Quick Start

```bash
# Run without installing (or `pip install erdify`)
uvx erdify ./src/database -o erd.puml
```

```bash
# Output to stdout, with a custom title
erdify ./src/models --title "My Database Schema"
```

See the [documentation](https://github.com/devsuit-berlin/erdify/blob/main/docs/index.md) for installation options, the full CLI, the Python API and more.

## 🧬 One Schema, Five Frameworks

The snippets below all describe the **same** `User` / `Order` schema — only the
syntax differs. Each one produces the **identical** diagram:

![Framework comparison ERD](https://raw.githubusercontent.com/devsuit-berlin/erdify/main/docs/examples/erd.png "The same ERD from all five frameworks")

> ℹ️ The SQLModel, SQLAlchemy and Django versions declare keys explicitly (Django
> via its implicit `id` and `ForeignKey`). Pydantic and dataclasses have no key
> concept, so they are rendered with [`--infer-keys`](https://github.com/devsuit-berlin/erdify/blob/main/docs/usage/filtering.md#inferring-keys---infer-keys)
> (`id` → PK, `<x>_id` → FK) to match. The runnable sources live in
> [`docs/examples/`](https://github.com/devsuit-berlin/erdify/tree/main/docs/examples).

<table>
<tr><th>SQLModel</th><th>SQLAlchemy 2.0</th></tr>
<tr><td>

```python
from sqlmodel import (
    Field, Relationship, SQLModel,
)


class User(SQLModel, table=True):
    __tablename__: str = "user"
    id: int = Field(primary_key=True)
    name: str
    email: str
    orders: list["Order"] = Relationship(
        back_populates="user")


class Order(SQLModel, table=True):
    __tablename__: str = "order"
    id: int = Field(primary_key=True)
    user_id: int = Field(
        foreign_key="user.id")
    total: float
    user: "User" = Relationship(
        back_populates="orders")
```

</td><td>

```python
from sqlalchemy import ForeignKey
from sqlalchemy.orm import (
    DeclarativeBase, Mapped,
    mapped_column, relationship,
)


class Base(DeclarativeBase): ...


class User(Base):
    __tablename__ = "user"
    id: Mapped[int] = mapped_column(
        primary_key=True)
    name: Mapped[str] = mapped_column()
    email: Mapped[str] = mapped_column()
    orders: Mapped[list["Order"]] = (
        relationship(back_populates="user"))


class Order(Base):
    __tablename__ = "order"
    id: Mapped[int] = mapped_column(
        primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("user.id"))
    total: Mapped[float] = mapped_column()
    user: Mapped["User"] = relationship(
        back_populates="orders")
```

</td></tr>
<tr><th>Pydantic <code>--infer-keys</code></th><th>Dataclass <code>--infer-keys</code></th></tr>
<tr><td>

```python
from pydantic import BaseModel


class User(BaseModel):
    id: int
    name: str
    email: str
    orders: list["Order"] = []


class Order(BaseModel):
    id: int
    user_id: int
    total: float
    user: "User"
```

</td><td>

```python
from dataclasses import dataclass, field


@dataclass
class User:
    id: int
    name: str
    email: str
    orders: list["Order"] = field(
        default_factory=list)


@dataclass
class Order:
    id: int
    user_id: int
    total: float
    user: "User" = None
```

</td></tr>
<tr><th colspan="2">Django ORM</th></tr>
<tr><td colspan="2">

```python
from django.db import models


class User(models.Model):       # implicit `id` PK; CharField/EmailField -> str
    name = models.CharField(max_length=100)
    email = models.EmailField()

    class Meta:
        db_table = "user"


class Order(models.Model):
    user = models.ForeignKey(    # -> user_id : int foreign key column
        User, on_delete=models.CASCADE)
    total = models.FloatField()  # -> float

    class Meta:
        db_table = "order"
```

</td></tr>
</table>

**How each framework is detected & parsed:**

| Framework | Detected by | Keys | Relationships |
| --------- | ----------- | ---- | ------------- |
| SQLModel | `table=True` | `Field(primary_key=…, foreign_key=…)` | `Relationship()` |
| SQLAlchemy 2.0 | `__tablename__` + `Mapped[...]` columns | `mapped_column(primary_key=…)`, `ForeignKey(...)` | `relationship()` (lowercase) |
| Django ORM | `models.Model` subclass | `primary_key=True` or implicit `id`, `ForeignKey`/`OneToOneField` | `ForeignKey` (N:1), `OneToOneField` (1:1), `ManyToManyField` (M:N, incl. `through=`) |
| Pydantic | `BaseModel` subclass (incl. transitive) | `--infer-keys` only | nested model refs (`user: User`, `list["Order"]`) |
| Dataclass | `@dataclass` decorator | `--infer-keys` only | nested model refs |

> ℹ️ Mixins / abstract bases (e.g. a SQLAlchemy mixin without `__tablename__`,
> or a Django `class Meta: abstract = True` base) are not drawn as tables, but
> their columns are inherited into concrete entities.

For a worked example with the generated PlantUML, see the [Frameworks Overview](https://github.com/devsuit-berlin/erdify/blob/main/docs/frameworks/index.md); for Django specifics see [Django ORM](https://github.com/devsuit-berlin/erdify/blob/main/docs/frameworks/django.md).

## 📚 Documentation

- [Installation](https://github.com/devsuit-berlin/erdify/blob/main/docs/installation.md) — pip, uv, pipx, or run with uvx
- [CLI & Python API](https://github.com/devsuit-berlin/erdify/blob/main/docs/usage/cli.md) — all CLI options, running as a module, and the Python API
- [Output Formats](https://github.com/devsuit-berlin/erdify/blob/main/docs/usage/output-formats.md) — PlantUML & Mermaid, `--format`, output naming
- [Filtering & Key Inference](https://github.com/devsuit-berlin/erdify/blob/main/docs/usage/filtering.md) — `--exclude`, `--exclude-paths`, `--sources`, `--infer-keys`
- [Viewing the Diagram](https://github.com/devsuit-berlin/erdify/blob/main/docs/usage/viewing.md) — render online, locally with PlantUML, or in VS Code
- [CI/CD & pre-commit](https://github.com/devsuit-berlin/erdify/blob/main/docs/usage/ci.md) — automate ERD generation in CI and on commit
- [Frameworks Overview](https://github.com/devsuit-berlin/erdify/blob/main/docs/frameworks/index.md) — a worked example with the generated PlantUML output
- [Django ORM](https://github.com/devsuit-berlin/erdify/blob/main/docs/frameworks/django.md) — Django-specific parsing details

## 📋 Supported Features

| Feature | Status | Notes |
| -------- | -------- | ------- |
| Primary Keys | ✅ | `Field(primary_key=True)` |
| Foreign Keys | ✅ | `Field(foreign_key="table.column")` |
| Nullable Fields | ✅ | `str \| None` or `Optional[str]` |
| Default Values | ✅ | `Field(default=value)` |
| Indexes | ✅ | `Field(index=True)` |
| Enums | ✅ | Python `Enum` classes |
| Relationships | ✅ | `Relationship()` |
| Inheritance | ✅ | Mixin classes supported |
| Link Tables | ✅ | Many-to-many detection |
| Custom Table Names | ✅ | `__tablename__` attribute |
| Exclude Patterns | ✅ | `--exclude` glob on class/table name |
| Key Inference | ✅ | `--infer-keys` for Pydantic/dataclass (`id`, `<x>_id`) |
| SQLModel | ✅ | `Field()` / `Relationship()` |
| SQLAlchemy 2.0 | ✅ | `Mapped[...]` / `mapped_column()` |
| Pydantic | ✅ | `BaseModel` subclasses, nested refs as relationships |
| Dataclass | ✅ | `@dataclass`, nested refs as relationships |

## 🗺️ Roadmap

Recently shipped:

| Feature | Status | Description |
| -------- | -------- | ------- |
| Exclude Option | ✅ Done | Exclude tables or entities from ERD generation using glob patterns |
| SQLAlchemy Support | ✅ Done | Native support for SQLAlchemy 2.0 (`Mapped` / `mapped_column`) models |
| Pydantic Support | ✅ Done | Generate ERDs from Pydantic models, with optional `--infer-keys` |
| Dataclass Support | ✅ Done | Support for standard Python dataclasses with type annotations |

Have a feature request? Please open an issue on [GitHub](https://github.com/devsuit-berlin/erdify/issues) to discuss it!

## 🤝 Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](https://github.com/devsuit-berlin/erdify/blob/main/CONTRIBUTING.md) for guidelines.

## 🔒 Security

For security concerns, please see [SECURITY.md](https://github.com/devsuit-berlin/erdify/blob/main/SECURITY.md).

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](https://github.com/devsuit-berlin/erdify/blob/main/LICENSE) file for details.

## 🙏 Acknowledgments

erdify stands on the shoulders of great open-source projects:

**Supported model frameworks**

- [SQLModel](https://sqlmodel.tiangolo.com/) - The awesome SQL database library
- [SQLAlchemy](https://www.sqlalchemy.org/) - The Python SQL toolkit and ORM
- [Django](https://www.djangoproject.com/) - The web framework whose ORM models erdify parses
- [Pydantic](https://docs.pydantic.dev/) - Data validation using Python type hints
- [dataclasses](https://docs.python.org/3/library/dataclasses.html) - Python standard-library data classes

**Rendering & output**

- [PlantUML](https://plantuml.com/) - For the diagram rendering
- [Graphviz](https://graphviz.org/) - Layout engine behind PlantUML's ER diagrams

**Tooling & infrastructure**

- [uv](https://docs.astral.sh/uv/) - Packaging, builds and dependency management
- [Ruff](https://docs.astral.sh/ruff/) - Linting and formatting
- [mypy](https://mypy-lang.org/) - Static type checking
- [pytest](https://docs.pytest.org/) - Testing framework
- [pre-commit](https://pre-commit.com/) - Git hook management

**Community**

- [Contributor Covenant](https://www.contributor-covenant.org/) - Our Code of Conduct
- [Keep a Changelog](https://keepachangelog.com/) - Changelog format
- And everyone who [contributes](https://github.com/devsuit-berlin/erdify/blob/main/CONTRIBUTING.md) issues, ideas and pull requests 💜

---

Made with ❤️ by [Devsuit GmbH](https://github.com/devsuit-berlin)
