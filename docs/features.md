---
description: "The full matrix of what erdify recognizes per framework: primary and foreign keys, relationships, enums, link tables, inheritance and type mapping."
---

# Supported Features

The full matrix of what erdify recognizes when parsing your models. For how each
framework is detected and a worked example, see the
[Frameworks Overview](frameworks/index.md).

| Feature | Status | Notes |
| -------- | -------- | ------- |
| Primary Keys | ✅ | `Field(primary_key=True)` |
| Foreign Keys | ✅ | `Field(foreign_key="table.column")` |
| Nullable Fields | ✅ | `str \| None`, `None \| str`, `Optional[str]`, `Union[str, None]` (also inside `Mapped[...]` / `Annotated[...]`), explicit `nullable=` (overrides the annotation), Django `null=True`; a nullable FK, or an optional model reference (`user: User \| None`), is drawn optional (`}o--o\|`), and so is a SQLAlchemy / SQLModel to-one reference from the referenced side of a one-to-one. A primary key is never nullable, so SQLModel's `id: int \| None = Field(default=None, primary_key=True)` renders as a plain PK |
| Unique Columns | ✅ | `Field(unique=True)`, `mapped_column(unique=True)`, Django `unique=True` (and every `OneToOneField`) or a single-field `Meta.constraints` `UniqueConstraint` / `Meta.unique_together` entry, or a single-column `UniqueConstraint` / `Index(..., unique=True)` in `__table_args__`; SQL `UNIQUE` or a single-column `CREATE UNIQUE INDEX`; marked `UK`, and a unique FK is drawn 1:1 (`\|o--\|\|`). An FK that is its table's only primary-key column (shared primary key, incl. Django `ForeignKey` / `OneToOneField(primary_key=True)`) is drawn 1:1 too. A member of a composite primary key keeps its own uniqueness (`UK`, 1:1) |
| Default Values | ✅ | `Field(default=value)` |
| Indexes | ✅ | `Field(index=True)` — detected and emitted in `--format json`; not drawn in the PlantUML/Mermaid diagram |
| Enums | ✅ | Subclasses of `Enum`, `IntEnum`, `StrEnum`, `Flag` / `IntFlag`, also through a project's own enum base; Django `TextChoices` / `IntegerChoices` |
| Relationships | ✅ | `Relationship()` / `relationship()`, model references, Django relation fields; a relationship declared on both models is one edge, paired exactly by `back_populates=` |
| Inheritance | ✅ | Mixin classes supported; a redeclared attribute resolves like Python's MRO (Django: as Django copies abstract-base fields, first copy wins; a plain non-Model mixin adds no columns), and a class extending an earlier class of the same name inherits its fields. Django multi-table inheritance is drawn as a `<parent>_ptr_id` 1:1 link; proxy models are not drawn. SQLAlchemy joined-table subclasses get only their own table's columns; single-table subclasses add their columns to the parent's table (their relationships are not drawn yet, [#317](https://github.com/devsuit-berlin/erdify/issues/317)) |
| Link Tables | ✅ | Many-to-many detection (structural) |
| Custom Table Names | ✅ | `__tablename__` attribute; without one, SQLModel's default, the lower-cased class name (`HeroTeam` → `heroteam`) |
| Exclude Patterns | ✅ | `--exclude` glob on class/table name |
| Key Inference | ✅ | `--infer-keys` for Pydantic/dataclass (`id`, `<x>_id`) |
| File Discovery | ✅ | `--include` globs (`models/` packages, custom filenames) |
| Markdown Embed | ✅ | `--inject` into Markdown between `erdify:start`/`erdify:end` markers |
| SQLModel | ✅ | `Field()` / `Relationship()`, also a `Field()` in `Annotated[...]` metadata (as SQLModel 0.0.32+ reads it); an explicit column name from `sa_column=Column("col", ...)` / `sa_column_kwargs={"name": "col"}` |
| SQLAlchemy 2.0 | ✅ | `Mapped[...]` (also qualified, `orm.Mapped[...]`, and `WriteOnlyMapped` / `DynamicMapped`) / `mapped_column()`, also inside `Annotated[...]` metadata, returned by a `@declared_attr` method (also a `relationship()`, e.g. on a mixin), and through module-level column type aliases (`intpk = Annotated[int, mapped_column(primary_key=True)]`); an explicit column name (`mapped_column("col")` / `name=`) names the column, and `x: Mapped[T] = <plain value>` is not a column (as in SQLAlchemy); any declarative base (`DeclarativeBase`, `declarative_base()`, `@registry.mapped`); module-level Core `Table(...)` tables (association tables as link tables), classes mapped with `__table__ = Table(...)` or `registry.map_imperatively()` (see [Limitations](frameworks/limitations.md#tables-declared-outside-a-class-body)) |
| Django ORM | ✅ | `models.Model`, `ForeignKey` / `OneToOneField` / `ManyToManyField`; `CompositePrimaryKey`; default table names `<app_label>_<model>`, `Meta.db_table` / `app_label` also inherited from an abstract base; `db_column`; custom user models on `AbstractUser` / `AbstractBaseUser` + `PermissionsMixin` get the inherited fields; relations to `auth.User`, `settings.AUTH_USER_MODEL` and other `django.contrib` models reference their real tables |
| Pydantic | ✅ | `BaseModel` subclasses, nested refs as relationships; `--base-classes` adds bases defined outside the scan (e.g. django-ninja's `Schema`) |
| Dataclass | ✅ | `@dataclass`, nested refs as relationships |
| SQL DDL | ✅ | via `erdify[sql]` (sqlglot 30.8+); `CREATE TABLE` + FK/PK + `NOT NULL` / `NULL` + enums; names resolved as the dialect folds them; `CREATE UNIQUE INDEX` makes a column unique, other `CREATE INDEX` is JSON-only (see Indexes note above); [details](frameworks/sql.md) |
