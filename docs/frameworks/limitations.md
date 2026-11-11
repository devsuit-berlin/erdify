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

## Classic `Column()` attributes are not read

Only SQLAlchemy 2.0's annotated style (`id: Mapped[int] = mapped_column(...)`)
is read. Classic declarative attributes (`id = Column(Integer, ...)`) have no
annotation, so they are not drawn as columns. A class needs at least one
`Mapped[...]` (or `WriteOnlyMapped` / `DynamicMapped`) member of its own to be
detected; one mixing both styles shows only its `Mapped` columns.

## Column type aliases

SQLAlchemy column type aliases are resolved like Python resolves the name when
the class body runs: a module-level `Annotated[...]` alias whose metadata
holds a `mapped_column(...)` (`intpk = Annotated[int,
mapped_column(primary_key=True)]`, also `X: TypeAlias = ...`, a re-export
`UserId = intpk`, or one built on another alias: `Annotated[intpk, ...]`).

- In the model's module, the name's last module-level binding **before the
  class** counts; a rebinding after it does not.
- An import is followed into the scanned file it names: relative, absolute
  (when several scanned files match, the one in the importing file's package
  wins; if that still leaves several, the alias applies only if all of them
  define the same one), renamed, or `*` (in order, honouring `__all__`, and through further
  star imports). An import from elsewhere (`from uuid import UUID`), a
  function, a class or any other binding means the name is not an alias there.
- A name the module does not bind at all (e.g. imported under
  `TYPE_CHECKING`) uses the alias of that name if it is defined identically
  wherever it is defined and is not a model class's name, also when it is
  built on another alias (`UserId = intpk`).
- Only module-level statements count, not ones inside `if` / `try` blocks. A
  module-qualified alias (`Mapped[coltypes.intpk]`) is not expanded.
- Other `Annotated` aliases (e.g. Pydantic's `PositiveInt`) keep their name as
  the type. A PEP 695 `type X = ...` alias is not read, since SQLAlchemy does
  not take a `mapped_column()` from it, and neither is a subscripted one
  (`Pk[int]`).
- Only SQLAlchemy models read this metadata; SQLModel, Pydantic and dataclass
  fields keep the alias name and get no settings from it.
- The defining module must be scanned: with the default `--include models.py`,
  aliases in `coltypes.py` are only found with `--include '**/*.py'` (or a
  pattern that matches the file).

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
it. A type alias for a relationship (`Mapped[ChildList]`) is taken as a class
name, so it draws an edge only if a model of that name exists.
A module-qualified name (`schemas.User`) resolves by its last part inside `relationship()` /
`Relationship()`; on a plain Pydantic / dataclass field it stays a column,
because it may be an external class that shares a model's name.

Django is the exception: its relationship fields are calls, so string targets
(`"Author"`, `"catalog.Author"`, `"self"`) and direct class references are all
resolved from the call argument.

## Both sides of a relationship

A relationship declared on both models (`User.posts` and `Post.user`) is drawn
as **one edge**. Each end shows what its own side declares: `list[Post]` on
`User` and `user: User | None` on `Post` give `Post }o--o| User`, and a list on
both sides gives `}o--o{`. The edge is drawn from the model whose name sorts
first (by code point, so case-sensitive) and labelled with that side's
attribute; for a self-reference, from the attribute whose name sorts first. So
the edge's text does not depend on file order (its position among the other
edges still follows the models' order). Within a model, a guessed pair can
still change when you reorder ambiguous declarations, since ties go by
declaration order (see below); `back_populates` removes the ambiguity.

Which two attributes form a pair:

- **Named explicitly:** a SQLAlchemy / SQLModel `back_populates=` (also in
  SQLModel's `sa_relationship_kwargs`) pairs exactly with the attribute it
  names; mutual declarations win over one-sided ones. A name the other model
  does not declare is ignored and the pair is guessed. (`backref=` and
  Django's `related_name` create the other side implicitly, so there is
  nothing to pair.)
- **Guessed** for everything else, e.g. Pydantic and dataclass models, which
  have no such marker. Each reference of the model whose name sorts first folds
  at most one reference declared back from the other model, preferring the
  inverse cardinality (a `list[Post]` pairs with a `User` reference) and
  attributes named after the class they point at (`Post.user` / `User.posts`,
  also `categories` for `Category`); ties go by declaration order.
  - Every reference left over gets its own edge, so `Post.author` beside
    `Post.user` is a second edge.
  - A reference back with a *different* cardinality is folded too, because it
    may be the other side of a 1:1 (`User.profile` / `Profile.user`), and is
    then drawn 1:1 (`||--||`). Two independent references in opposite
    directions (`User.pinned_post` and `Post.author`) therefore show as one
    1:1 edge; use `back_populates` where the framework has it to keep them
    apart.
  - A self-reference has no other model, so only an N:1 / 1:N inverse is
    folded: `Node.parent` and `Node.children` are one edge, while
    `Employee.manager` and `Employee.mentor`, or two `ManyToManyField("self")`
    fields, stay two.

A foreign-key column already draws the edge between two models, so their
declared relationships (which usually mirror it) are not drawn again. A
many-to-many is the exception: it never mirrors a foreign-key column, so a
Django `ManyToManyField` is drawn even when a foreign key also connects the
two models.

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
| Django app label from an `AppConfig` named in `INSTALLED_APPS` (`"shop.apps.Custom"`), or a non-literal `label` | The app's default `AppConfig` or the package name is used |
| Django `Meta.db_table` / `Meta.app_label` inherited from an abstract base | Not read yet ([#279](https://github.com/devsuit-berlin/erdify/issues/279)) |
| Django table names longer than the database's identifier limit | Shown in full; Django truncates them per backend (e.g. 63 characters on PostgreSQL) |
| Composite foreign keys | Not supported |
| Foreign keys inside `sa_column=Column(...)` | Not detected |
| Unannotated `x = relationship("Target")` | Not detected |
| ninja-style `ModelSchema` (fields from an inner `Meta`/`Config`) | Detected and skipped with a warning, rather than drawn empty ([#171](https://github.com/devsuit-berlin/erdify/issues/171)) |
| `attrs` / `msgspec` models | Not supported ([erdantic](../comparison.md) covers these) |
| Live database introspection | Not supported by design |

Hitting one of these in a way that looks fixable within the AST approach? Please
[open an issue](https://github.com/devsuit-berlin/erdify/issues) — several of
these are "not implemented yet" rather than "impossible".
