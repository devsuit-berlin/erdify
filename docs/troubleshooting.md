---
description: "Symptom-first fixes for erdify — models not found, too many entities, missing relationships, and missing keys on Pydantic or dataclass models."
---

# Troubleshooting

Start from the symptom.

## "No tables found"

```
Warning: No tables found in ./src
  Scanned 42 .py/.sql file(s); 0 matched --include 'models.py'.
```

The second line is the diagnosis. Read the two numbers:

**`0 matched`** — the scan never opened a file with your models in it. Almost
always the default `--include`:

| Cause | Fix |
|---|---|
| Models live in `schema.py`, `tables.py`, `entities.py`, … | `--include schema.py` — this **replaces** the default, so list `models.py` too if you still want it |
| Models split across a `models/` package | `--include '**/models/*.py'` |
| SQL DDL files | `--include '*.sql'` (and install `erdify[sql]`) |
| The path you passed is above or beside the code | Point `input` at the directory that actually contains the models |
| Files are under a directory erdify prunes (`.venv`, `site-packages`, `node_modules`, `.tox`, …) | `--no-default-excludes` |
| You are excluding them yourself | Check `--exclude-paths` and `[tool.erdify] exclude_paths` |

**`N matched` with `N > 0`** — the files were read but nothing in them looked
like a model:

- The classes are not one of the five recognized frameworks. See
  [Frameworks Overview](frameworks/index.md).
- They inherit from a base class defined **outside** the scanned files — the
  django-ninja `Schema`, or a shared `BaseSchema` from an internal library.
  erdify cannot resolve that chain; name the base with
  [`--base-classes`](usage/cli.md#bases-defined-outside-the-scan-base-classes).
- SQLModel classes are missing `table=True` (a model without it is not a table).
- `--sources` is narrower than you think: `--sources sqlmodel` drops your Django
  models silently.
- `--exclude` removed them after parsing — try without it.
- The models are built at runtime; see
  [Python parsing limitations](frameworks/limitations.md).

Since 0.13.0 an empty result exits `1` and writes nothing, so a CI job fails
here instead of committing an empty diagram over a good one. If an empty schema
is legitimate for your project, pass
[`--allow-empty`](usage/cli.md#empty-results-allow-empty).

## Too many entities

The diagram is unreadable, or it contains other people's models.

| Symptom | Fix |
|---|---|
| Third-party models from a virtualenv | They should already be pruned; if you passed `--no-default-excludes`, drop it |
| Django migrations, legacy or experimental apps | `--exclude-paths migrations legacy 'apps/experimental/*'` |
| Audit/log/link tables you do not want to show | `--exclude audit_log '*Link'` (matches class **or** table name, case-sensitive) |
| Pydantic DTOs mixed in with real tables | `--sources sqlmodel sqlalchemy django` |
| Enum blocks dominate the picture | `--no-enums` |

Details: [Filtering & Key Inference](usage/filtering.md).

## No relationships drawn

Entities appear, but the diagram has no lines.

1. **Is the target entity in the diagram?** A foreign key whose target class was
   never parsed produces a column and no line. Widen `--include` so both sides
   are scanned. This is the most common cause.
2. **Did `--exclude` remove one end?** Excluding an entity also removes its
   edges.
3. **`--no-relationships` set?** Check the flag and `[tool.erdify]`.
4. **Is the relationship expressed in a way the parser reads?** An unannotated
   `x = relationship("Target")`, a foreign key hidden in `sa_column=Column(...)`,
   or a composite key in `__table_args__` are all invisible. See
   [Python parsing limitations](frameworks/limitations.md).
5. **Tables in database schemas?** A foreign key naming a schema
   (`core.customer`) is drawn to the table in that schema or, when that schema
   has no such table, to a same-name table declared without a schema, never to
   one in another schema. With neither (not scanned, or excluded), there is no
   line. An unqualified reference
   to a table name that exists in several schemas, none of them preferred, is
   ambiguous and draws none either. See
   [Schemas in references](frameworks/sql.md#supported-ddl-subset) and the
   [`__table_args__` schema note](frameworks/limitations.md#__table_args__-is-mostly-not-read). erdify warns on
   stderr when two SQL tables differ only in quoting; a SQL table hidden by a
   Python model of the same name is dropped without a warning.
6. **Same-name classes in several modules?** Two model classes called
   `Address` are drawn as `billing.models.Address` and
   `shipping.models.Address`. A reference to `Address` in a file that neither
   defines nor imports one of them can't be told apart: it is not drawn, and
   erdify names the candidates on stderr. Import the class you mean.
7. **Pydantic or dataclass models?** They have no keys until you pass
   `--infer-keys` (next section).

## No keys on my Pydantic / dataclass models

Expected: these frameworks have nothing to read. A dataclass field named `id` is
just a field.

```bash
erdify ./app --infer-keys
```

`--infer-keys` treats a field named `id` as the primary key and `<x>_id` as a
foreign key to table `<x>`. It is a naming heuristic, so check the result: a
field like `external_id` becomes a foreign key to a table named `external`.
Limit the damage with `--sources` or `--exclude` if that happens.

## The table name is wrong

erdify only reads a **literal** `__tablename__` / `Meta.db_table`. A computed
one falls back to the class-name conversion without warning — see
[Python parsing limitations](frameworks/limitations.md#non-literal-__tablename__).

## `--check` fails but the diagram looks identical

`--check` compares the text exactly (only trailing newlines are ignored), so
a changed `--title`, a different flag set, or another erdify version between
your local run and CI is enough. Make sure both run
the *same* command — the cleanest way is to put the settings in
`[tool.erdify]` and run plain `erdify .` everywhere.

## `.sql` files are ignored

The SQL frontend needs the extra and an include pattern that matches:

```bash
pip install 'erdify[sql]'
erdify ./schema --include '*.sql' --sql-dialect postgres
```

Without `--sql-dialect`, sqlglot parses in a permissive generic mode and
dialect-specific constructs such as `CREATE TYPE … AS ENUM` are not recognized.
See the [SQL DDL frontend](frameworks/sql.md).

## Still stuck: look at what was parsed

```bash
erdify ./app --format json
```

The JSON is the intermediate representation the renderers consume — every
entity, field, key and relationship erdify found. If something is missing there,
it is a parsing problem, not a rendering one.

Still wrong? [Open an issue](https://github.com/devsuit-berlin/erdify/issues)
with a minimal model file that reproduces it.
