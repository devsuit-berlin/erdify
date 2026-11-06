---
description: "What the AST parser cannot see in Python models — runtime-constructed classes, most of __table_args__, composite foreign keys, sa_column — and what to do about each."
---

# Python Parsing Limitations

erdify reads your models with the standard library's `ast` module. It never
imports them, so it sees **the text of the file, not the classes Python would
build from it**. Almost every limitation below follows from that one fact.

The [SQL DDL frontend](sql.md#deferred-not-supported) has its own list.

!!! tip "How to tell"
    Render to `--format json` and look at what erdify actually extracted. It is
    the fastest way to confirm whether a field, key or relationship was seen.
    See [Troubleshooting](../troubleshooting.md).

## Only scanned files exist

Class names, relationship targets and foreign keys are resolved **within the set
of files the scan selected**. `--include` defaults to `models.py`, so a model
that lives anywhere else is invisible — and a relationship pointing at it
silently produces no line:

```python
# app/models.py                     # other/entities.py holds Team
class Hero(SQLModel, table=True):
    team_id: int = Field(foreign_key="team.id")
    team: Optional["Team"] = Relationship()
```

erdify draws `Hero` with a `foreign_key(team_id)` column and **no relationship
to `Team`**, because `Team` was never parsed. Widen the scan:

```bash
erdify . --include models.py entities.py
```

## Anything built at runtime

| Construct | What erdify does |
|---|---|
| `Model = type("Model", (SQLModel,), {...})` | Invisible — there is no `class` statement to walk. |
| A class defined inside a factory function | Picked up, but under its **source** name: `class _Generated` inside `make_model()` becomes entity `_Generated` / table `__generated`, not whatever the factory returns. |
| Fields attached with `setattr()` or in a loop | Invisible. Only class-body assignments and annotations are read. |
| Fields under `if TYPE_CHECKING:` | Invisible. |
| Models registered by a third-party package | Invisible unless their source is in the scanned files. |
| A **base class** defined outside the scan (`ninja.Schema`, a shared internal `BaseSchema`) | Its subclasses are skipped, because the inheritance chain to `BaseModel` cannot be resolved. Name it with [`--base-classes`](../usage/cli.md#bases-defined-outside-the-scan-base-classes). |

If your schema is genuinely assembled at runtime, an import-based tool is the
right instrument — see the [comparison](../comparison.md).

## Non-literal `__tablename__`

The table name is read only when it is a string literal. Anything else falls
back to the class-name conversion, **without a warning**:

```python
class Computed(SQLModel, table=True):
    __tablename__ = "prefix_" + "computed"   # erdify reports: computed
```

The same applies to a `declared_attr`-computed `__tablename__`. Django's
`Meta.db_table` *is* read when it is a literal.

## `__table_args__` is mostly not read

Only single-column uniqueness inside `__table_args__` reaches the diagram:

```python
class Match(Base):
    __table_args__ = (
        ForeignKeyConstraint(["season_year", "season_league"],
                             ["season.year", "season.league"]),
        UniqueConstraint("slug"),
        Index("ix_match_played_at", "played_at"),
    )
```

- **Composite foreign keys** are missed entirely — the columns appear as plain
  columns and no relationship is drawn. (Composite *primary* keys are fine; see
  below.)
- A single-column `UniqueConstraint("col")` or `Index("ix", "col", unique=True)`
  marks `col` as unique (`UK`, and 1:1 when it is a foreign key). A string
  names the database column, so it matches an explicit name set with
  `mapped_column("col", ...)`, `mapped_column(..., name="col")`,
  `Field(sa_column=Column("col", ...))` or `Field(sa_column_kwargs={"name": "col"})`;
  a bare reference (`UniqueConstraint(attr)`) names the attribute. Composite
  constraints, partial indexes (`postgresql_where=` / `sqlite_where=`) and
  non-unique `Index` entries are ignored; the index marker comes only from
  per-column `index=`. `__table_args__` is read only when it is assigned
  directly in the model class: one inherited from a mixin or returned by a
  `@declared_attr` method is not seen.
- `schema=` is ignored; entities are not namespaced.

Django's `Meta.unique_together` and `Meta.indexes` are ignored for the same
reason.

## Composite keys

**Composite primary keys work.** Several columns marked `primary_key=True` are
all rendered as primary keys, and the structural link-table detection depends on
exactly that.

**Composite foreign keys do not**, because SQLAlchemy can only express them
through `__table_args__` (above). A multi-column foreign key produces plain
columns and no relationship line.

## Foreign keys hidden in `sa_column`

erdify reads the foreign key from `Field(foreign_key="team.id")`,
`mapped_column(ForeignKey("team.id"))` and Django's relationship fields. It does
**not** look inside a `sa_column=Column(...)`:

```python
# not detected
team_id: Optional[int] = Field(default=None, sa_column=Column(Integer, ForeignKey("team.id")))

# detected
team_id: Optional[int] = Field(default=None, foreign_key="team.id")
```

## Relationships need an annotation

The relationship target comes from the **annotation**, not from the call
argument. An annotated attribute works whether the target is a real name or a
string; a bare assignment is ignored:

```python
annotated: Mapped["Coach"] = relationship("Coach")   # drawn
bare = relationship("Coach")                          # ignored
```

The annotation must name **exactly one class**, possibly optional (`X | None`,
`Optional[X]`, `Union[X, None]`), wrapped (`Mapped`, `Annotated`), or in a
collection (`list`, `set`, `Sequence`, `Iterable`, `tuple[X, ...]`, a mapping's
value, and SQLAlchemy's collection-only `WriteOnlyMapped` / `DynamicMapped`). A union of several classes
(`Mapped[Union["Cat", "Dog"]]`) names no single class, so nothing is drawn for
it. A type alias (`Mapped[ChildList]`) is taken as a class name, so it draws an
edge only if a model of that name exists. A module-qualified name
(`schemas.User`) resolves by its last part inside `relationship()` /
`Relationship()`; on a plain Pydantic / dataclass field it stays a column,
because it may be an external class that shares a model's name.

Django is the exception: its relationship fields are calls, so string targets
(`"Author"`, `"catalog.Author"`, `"self"`) and direct class references are all
resolved from the call argument.

## Both sides of a relationship

A relationship declared on both models (`User.posts` and `Post.user`) is drawn
once, from the model parsed first. erdify does not read `back_populates`, so it
pairs the two sides by guesswork: each edge of the first model absorbs one
reference declared back from the other model. It prefers the inverse
cardinality (a `list[Post]` on `User` pairs with a `User` reference on `Post`)
and then an attribute named after the class (`Post.user` for `User`).

- Every reference left over gets its own edge, so `Post.author` beside
  `Post.user` is a second edge.
- A reference back with a *different* cardinality is folded too, because it
  may be the other side of a 1:1 (`User.profile` / `Profile.user`). Two
  independent references in opposite directions (`User.pinned_post` and
  `Post.author`) therefore show as one edge.
- The kept edge shows the first model's cardinality only; the folded side's
  optionality is not merged in.
- A self-reference has no other model, so only an N:1 / 1:N inverse is
  folded: `Node.parent` and `Node.children` are one edge, while
  `Employee.manager` and `Employee.mentor`, or two `ManyToManyField("self")`
  fields, stay two.

A foreign-key column already draws the edge between two models, so their
declared relationships are not drawn again.

## Keyless models

Pydantic models and dataclasses have no keys to read. Without `--infer-keys`,
`id` and `<x>_id` stay ordinary columns and no relationships are drawn — see
[Filtering & Key Inference](../usage/filtering.md). Inference is a heuristic on
names, so it can be wrong in both directions.

## Deferred / Not supported

| Item | Status |
|------|--------|
| Runtime-constructed models (`type()`, registries) | Not supported by design (no imports) |
| Fields added via `setattr` / loops / `if TYPE_CHECKING` | Not supported |
| Non-literal `__tablename__` / `declared_attr` | Falls back to the class name, silently |
| `__table_args__` (composite FKs, composite `UniqueConstraint`, partial or non-unique `Index`, `schema=`) | Not read; single-column `UniqueConstraint` / unique `Index` is read |
| Django `Meta.unique_together` / `Meta.indexes` | Not read |
| Composite foreign keys | Not supported |
| Foreign keys inside `sa_column=Column(...)` | Not detected |
| Unannotated `x = relationship("Target")` | Not detected |
| ninja-style `ModelSchema` (fields from an inner `Meta`/`Config`) | Detected and skipped with a warning, rather than drawn empty ([#171](https://github.com/devsuit-berlin/erdify/issues/171)) |
| `attrs` / `msgspec` models | Not supported ([erdantic](../comparison.md) covers these) |
| Live database introspection | Not supported by design |

Hitting one of these in a way that looks fixable within the AST approach? Please
[open an issue](https://github.com/devsuit-berlin/erdify/issues) — several of
these are "not implemented yet" rather than "impossible".
