---
description: "PlantUML, Mermaid, JSON and standalone HTML output from erdify, how --output extensions are normalized, and Markdown injection."
---

# Output Formats

erdify renders to four formats, chosen (one or more) with `--format`:

| Format | Extension | What it is |
| ------ | --------- | ---------- |
| `plantuml` (default) | `.puml` | PlantUML ERD source |
| `mermaid` | `.mmd` | Mermaid `erDiagram` source (renders natively on GitHub/GitLab) |
| `json` | `.json` | The parsed model as structured JSON, for downstream tools |
| `html` | `.html` | A self-contained page that draws the ERD with Mermaid |

```bash
erdify ./src/database --format mermaid -o docs/erd.mmd
erdify ./src/database --format plantuml mermaid -o docs/erd   # writes both
```

## How `--output` and extensions work

The extension of `-o` is **normalized to match the format**: erdify strips any
existing suffix and appends the format's extension (`.puml`, `.mmd`, `.json`,
`.html`). So `-o docs/erd`, `-o docs/erd.puml` and `-o docs/erd.txt` all produce
`docs/erd.puml` for PlantUML.

- One format, no `-o` → printed to stdout.
- Multiple formats → require `-o`; each is written to `<base>.<ext>`.
- `--check` validates **every** target file and exits non-zero if any is missing
  or stale.

Set a default in `pyproject.toml`:

```toml
[tool.erdify]
format = ["plantuml", "mermaid"]
output = "docs/erd"
```

## Mermaid

Mermaid `erDiagram` output renders natively on GitHub and GitLab, so you can
embed an ERD directly in Markdown without a PlantUML/Graphviz toolchain. The
left tab is what erdify writes to the `.mmd` file; the right tab is what GitHub
(and this page) draws from it:

=== "Source"

    ```
    erDiagram
        User {
            int id PK
            str name
            str email
        }
        Order {
            int id PK
            int user_id FK
            float total
        }
        Order }o--|| User : "user_id"
    ```

=== "Rendered"

    ```mermaid
    erDiagram
        User {
            int id PK
            str name
            str email
        }
        Order {
            int id PK
            int user_id FK
            float total
        }
        Order }o--|| User : "user_id"
    ```

Notes:

- Relationships use crow's-foot cardinalities identical to PlantUML
  (`}o--||` N:1, `||--o{` 1:N, `||--||` 1:1, `}o--o{` M:N). A unique
  single-column foreign key is a 1:1 rendered `|o--||` (NOT NULL FK) or
  `|o--o|` (nullable FK).
- A unique non-primary-key column is marked `UK` in the entity block,
  alongside `PK`/`FK`.
- Mermaid has no enum construct, so each used enum is rendered as an entity block
  listing its values; the referencing column keeps the enum name as its type.
- Attribute types are reduced to a single Mermaid-safe token (e.g. `list[str]`
  becomes `list_str`).

## JSON

`--format json` emits the parsed model as structured JSON — the integration
point for downstream tools that want erdify's model without re-parsing source.

```json
{
  "schema_version": 1,
  "title": "Database ERD",
  "entities": [
    {
      "name": "Order",
      "table_name": "order",
      "source": "sqlmodel",
      "is_link_table": false,
      "fields": [
        {"name": "id", "type": "int", "primary_key": true, "foreign_key": false,
         "nullable": false, "foreign_table": null, "index": false, "unique": false,
         "default": null}
      ],
      "relationships": [{"target": "User", "type": "one", "attribute": "user"}]
    }
  ],
  "enums": [{"name": "Status", "values": ["DRAFT", "PUBLISHED"]}]
}
```

### Schema

Top level:

| Key | Type | Description |
|---|---|---|
| `schema_version` | integer | Version of this document shape. Currently `1`. |
| `title` | string | The diagram title (`--title`). |
| `entities` | array of entity | One object per table / model. |
| `enums` | array of enum | Empty when enums are disabled (`--no-enums`). |

Entity:

| Key | Type | Description |
|---|---|---|
| `name` | string | Class name (or table name for SQL DDL). |
| `table_name` | string | Database table name. |
| `source` | string | One of `sqlmodel`, `sqlalchemy`, `django`, `dataclass`, `pydantic`, `sql`. |
| `is_link_table` | boolean | `true` for a detected many-to-many join table. |
| `fields` | array of field | Columns, in declaration order. |
| `relationships` | array of relationship | Empty when relationships are disabled (`--no-relationships`). |

Field:

| Key | Type | Description |
|---|---|---|
| `name` | string | Column / attribute name. |
| `type` | string | Type as written in the source (or the mapped Python type). |
| `primary_key` | boolean | Part of the primary key. |
| `foreign_key` | boolean | References another table. |
| `nullable` | boolean | Column accepts `NULL`. |
| `foreign_table` | string or null | Referenced `table.column` when `foreign_key` is `true`. |
| `index` | boolean | Column is indexed. |
| `unique` | boolean | Column has a unique constraint. |
| `default` | string or null | Default value as source text, if any. |

Relationship:

| Key | Type | Description |
|---|---|---|
| `target` | string | Name of the related entity. |
| `type` | string | One of `one`, `many`, `one_to_one`, `many_to_many`. |
| `attribute` | string | Attribute name on this entity. |

Enum:

| Key | Type | Description |
|---|---|---|
| `name` | string | Enum class name. |
| `values` | array of string | Enum members, in declaration order. |

### Compatibility

- **Adding** a key is non-breaking and does not change `schema_version`.
  Consumers must ignore keys they do not know.
- **Removing or renaming** a key, or changing a value's type or meaning, bumps
  `schema_version` and ships only in a major erdify release.
- Check `schema_version` before reading the document if your tool must fail
  loudly on an incompatible shape.

## HTML

`--format html` wraps the Mermaid diagram in a self-contained HTML page — open it
in a browser to view the ERD (double-click). It loads Mermaid from a **pinned
CDN** version, so it needs internet access to render. For offline/raster export,
render the `.mmd` with [`@mermaid-js/mermaid-cli`](https://github.com/mermaid-js/mermaid-cli)
or the `.puml` with PlantUML.

## Embedding the diagram in Markdown (`--inject`)

`--inject` writes the diagram into an existing markdown file between marker
comments, so it renders natively on GitHub/GitLab. Add the markers once:

```markdown
## Database

<!-- erdify:start -->
<!-- erdify:end -->
```

Then run:

```bash
erdify ./db --inject README.md
```

erdify replaces only the text between the markers — everything else in the file
is untouched. It uses a single `--format` (default `mermaid`, which renders on
GitHub); the fenced block's language follows the format. `--format html` and
multiple `--format` values are rejected with `--inject`.

Settable via config:

```toml
[tool.erdify]
inject = "README.md"
```

In CI or pre-commit, combine with `--check` to fail when the embedded diagram is
out of date (nothing is written):

```bash
erdify ./db --inject README.md --check
```

If the file is missing or has no `<!-- erdify:start -->` / `<!-- erdify:end -->`
markers, erdify errors and changes nothing.
