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
  (`}o--||` N:1, `||--o{` 1:N, `||--||` 1:1, `}o--o{` M:N). The parent end
  of a foreign-key edge follows the FK's nullability: a nullable FK is drawn
  `}o--o|` (the child may have no parent). A unique single-column foreign key
  is a 1:1 rendered `|o--||` (NOT NULL FK) or `|o--o|` (nullable FK), and so
  is a foreign key that is its table's only primary-key column (shared
  primary key).
- A model reference without a foreign key (Pydantic / dataclass, or a
  `relationship()` whose pair no FK column connects) typed as optional
  (`user: User | None`, `None | User`, `Optional[User]`, `Union[User, None]`,
  or any of these inside `Annotated[...]`) is drawn `}o--o|`, a required one
  (`user: User`) `}o--||`.
- A unique non-primary-key column is marked `UK` in the entity block,
  alongside `PK`/`FK`.
- Mermaid has no enum construct, so each used enum is rendered as an entity block
  listing its values; the referencing column keeps the enum name as its type.
- Attribute types are reduced to a single Mermaid-safe token (e.g. `list[str]`
  becomes `list_str`).
- Names with spaces or special characters are encoded, see below.

## Names with spaces or special characters

A SQL quoted identifier (`"Order Items"`), a Django `db_column` or a class
named like a Mermaid keyword (`Class`, `Style`, `One`, `To`) is not valid
diagram syntax as it is. erdify encodes such names so every format parses,
and shows the real name wherever the syntax allows it. JSON always keeps the
real names.

| Name in | Mermaid / HTML | PlantUML |
| ------- | -------------- | -------- |
| Entity / table, enum | Quoted (`"Order Items" {`) when it isn't one plain word or starts with a keyword | Real name as the display name, one-word alias (`entity "Order Items" as Order_Items`) |
| Column | Invalid characters become `_`, a leading digit or key (`pk`, `fk`, `uk`) gets a `_` prefix, and the real name leads the comment: `int Item_Key PK "Item Key"` | Real name; quoted in the macro when it holds `,`, `(`, `)`, `"` or `<` (`column("a,b")`) |
| Enum value | Same as a column: `enum in_progress "in progress"` | Real value |
| Relationship label, comment, default | Real text; `"`, `#`, `%`, `\`, `&`, `<`, `>` and `~` are written as Mermaid entity codes (`#quot;`, `#lt;`, ...), which Mermaid draws as the character | Real text; `"` and `<` as `&#34;` / `&#60;` |

- An encoded name that collides with another one (`"a b"` and `a_b` both
  become the PlantUML alias `a_b`, or an entity and an enum share a name) gets
  a `_2`, `_3`, ... suffix. A name that is valid as it is keeps it.
- Mermaid reads `direction TB` (`BT`, `LR`, `RL`) as a layout statement
  anywhere on a line, even inside quotes, so the space is written `#32;`.
- `--format html` HTML-escapes the Mermaid source in the page.
- PlantUML reads a backslash followed by `n` as a line break in any text; a
  name containing `\n` is drawn on two lines.

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
      "relationships": [
        {"target": "User", "type": "one", "attribute": "user", "nullable": false,
         "inverse": null}
      ]
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
| `type` | string | One of `one`, `many`, `one_to_one`, `many_to_many`. Django `ForeignKey` / `OneToOneField` are foreign-key columns, not relationships, so the parsers no longer emit `one_to_one`; it remains valid for a hand-built `EntityInfo`. |
| `attribute` | string | Attribute name on this entity. |
| `nullable` | boolean | Always present. `true` when a `one` relationship's annotation admits `None` (`user: User \| None`, `Optional[User]`, `Mapped[Optional["User"]]`); `false` otherwise, including every `many` / `many_to_many` relationship. |
| `inverse` | string or null | The other side's attribute, when the source names it (SQLAlchemy / SQLModel `back_populates=`); `null` otherwise. Added in 1.4.0. |

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
- These rules cover the document's *shape*. Its *content* follows what the
  parser recognizes: a bug fix may change values or move an item between
  `fields` and `relationships` (e.g. a Django `OneToOneField` became a
  `<name>_id` field in 1.2.0). Such changes are listed under **Output changes**
  in the changelog and do not bump `schema_version`.

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
