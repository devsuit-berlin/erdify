---
description: "How erdify compares to eralchemy, sqlalchemy-schemadisplay, erdantic, django-extensions graph_models and DBML/dbdiagram — and when to reach for one of those instead."
---

# erdify vs. the alternatives

Several tools draw ER diagrams for Python projects. They differ less in what
they *draw* than in what they **require to run**: a live database, an importable
application, a Graphviz toolchain — or, for erdify, nothing but the source
files.

This page is meant to be useful even when the answer is "use the other one".
Every alternative below wins at something erdify deliberately does not do.

## At a glance

| | **erdify** | [eralchemy](https://github.com/eralchemy/eralchemy) | [sqlalchemy-schemadisplay](https://github.com/fschulze/sqlalchemy_schemadisplay) | [erdantic](https://github.com/drivendataorg/erdantic) | [django-extensions `graph_models`](https://django-extensions.readthedocs.io/en/latest/graph_models.html) | [DBML / dbdiagram](https://dbml.dbdiagram.io/) |
|---|---|---|---|---|---|---|
| **Needs a live DB connection** | No | Optional (a DB URL is one of its inputs) | Optional (or bound metadata) | No | No | Only for `db2dbml` |
| **Imports/executes your code** | **No** — stdlib `ast` only | Yes (models must import) | Yes | Yes (classes must be importable) | Yes (full Django setup + app registry) | n/a — you write DBML by hand |
| **Frameworks read** | SQLModel, SQLAlchemy 2.0, Django, Pydantic, dataclasses, SQL DDL | SQLAlchemy (+ live DBs, `.er` files) | SQLAlchemy | Pydantic v1/v2, attrs, msgspec, dataclasses | Django | SQL dumps (Postgres, MySQL, MSSQL, Oracle, Snowflake, BigQuery) |
| **Runtime dependencies** | **None** (`sqlglot` only for the `sql` extra) | SQLAlchemy, + Graphviz/pygraphviz for images | SQLAlchemy, pydot, Pillow, Graphviz | pydantic, pygraphviz, typer, … + Graphviz | Django, + pydot/pygraphviz for images | Node.js 18+ |
| **System toolchain** | None | Graphviz for image output | Graphviz | Graphviz (pygraphviz builds against it) | Graphviz for image output | Node |
| **Text output formats** | PlantUML, Mermaid, JSON, standalone HTML | Mermaid, Graphviz `.gv`, its own `.er` markdown | — (pydot writes images) | Graphviz, D2 | Graphviz `.dot`, JSON | DBML, SQL |
| **Image output** | No (render the PlantUML/Mermaid yourself) | PNG, PDF, SVG | PNG (+ pydot formats) | PNG, SVG, PDF, … | PNG, SVG, PDF, … | via dbdiagram.io |
| **CI drift gate** | `--check` (non-zero exit on a stale diagram) | No | No | No | No | No |
| **Embeds into Markdown** | `--inject` between markers | No | No | No | No | No |
| **License** | MIT | Apache-2.0 | MIT | MIT | MIT | Apache-2.0 |

Versions checked while writing this page: eralchemy 1.7.0, sqlalchemy-schemadisplay 2.0,
erdantic 1.2.1, django-extensions (`main`), `@dbml/cli` 3.x. Please
[open an issue](https://github.com/devsuit-berlin/erdify/issues) if something
here has gone out of date — an inaccurate comparison is worse than none.

## The one axis that matters: does it run your code?

Everything else on that table follows from this.

**erdify parses source with the standard library's `ast` module.** It never
imports your modules, never builds a metadata registry, never opens a
connection. Consequences, good and bad:

- It runs against a repository it cannot install — another team's checkout, a
  half-migrated branch, a pull request in CI with no services started.
- It has **zero runtime dependencies**, so it cannot drag a conflicting
  SQLAlchemy or pydantic into your environment. `uvx erdify ./app` works on a
  machine with nothing installed.
- Nothing in your models executes, which matters when `models.py` reaches for
  settings, environment variables or a connection at import time.
- **It only sees what is written in the file.** Anything computed at runtime —
  models built by `type()`, tables named by an expression, fields attached in a
  loop — is invisible to it. See
  [Python parsing limitations](frameworks/limitations.md).

**The import-based tools see the real, fully-resolved schema**: every mixin
applied, every `declared_attr` evaluated, every dynamically registered model
present, every type as SQLAlchemy actually resolved it. That is strictly more
accurate — at the price of needing the application to import cleanly, which in
a CI job usually means installing its full dependency tree.

**Live introspection (eralchemy against a DB URL, `db2dbml`) is the most
accurate of all**, because it reads what the database really contains, migrations
and all. erdify deliberately does not do this: it answers "what does this code
say?", not "what is deployed?". Those are different questions, and drift between
them is often the thing you want to find.

## When to use something else

- **You want a PNG and do not want to run PlantUML or Mermaid.** eralchemy,
  sqlalchemy-schemadisplay, erdantic and `graph_models` all render images
  directly through Graphviz. erdify emits diagram *source* and stops there.
- **You need the deployed schema, not the code.** eralchemy against a database
  URL, or `db2dbml`.
- **Your models are attrs or msgspec.** erdantic supports both; erdify does not.
- **Your Django models rely heavily on runtime configuration** — swappable user
  models, apps assembled from settings, models registered by third-party
  packages. `graph_models` sees all of it because Django is actually loaded.
- **You want to design a schema before writing it.** DBML is a DSL you author by
  hand, and dbdiagram.io gives you a visual editor. It is a modelling tool, not
  a documentation generator: it does not read Python at all.
- **You want a hosted, clickable diagram for non-engineers.** dbdiagram.io.

## When erdify fits

- **One tool for a polyglot repository.** A Django service, a FastAPI service on
  SQLModel, and a `schema.sql` used by the analytics team produce the same
  diagram format from the same command. The other tools here each cover one
  framework.
- **Documentation that cannot silently rot.** `--inject` writes the diagram into
  a Markdown file between markers, and `--check` exits non-zero when it drifts,
  so a stale ERD fails a build instead of quietly misleading the next reader.
  None of the alternatives ship a drift gate.
- **Environments where installing the project is not on the table** — a docs
  pipeline, a pre-commit hook, a review of a repository you do not own.
- **Diagram-as-text workflows.** PlantUML and Mermaid are diffable and review
  well; Mermaid renders natively on GitHub and GitLab.
- **Supply-chain-sensitive installs.** Nothing to audit but the standard library.

## What erdify does not do, on purpose

- No database connection and no introspection of a live schema.
- No image rendering; use PlantUML, Mermaid or their CLIs.
- No round-tripping — erdify reads models and writes diagrams, never the reverse.
- No runtime awareness. If a construct is not visible in the source text, erdify
  does not see it; the [limitations page](frameworks/limitations.md) lists the
  cases this actually bites.
