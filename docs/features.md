# Supported Features

The full matrix of what erdify recognizes when parsing your models. For how each
framework is detected and a worked example, see the
[Frameworks Overview](frameworks/index.md).

| Feature | Status | Notes |
| -------- | -------- | ------- |
| Primary Keys | ✅ | `Field(primary_key=True)` |
| Foreign Keys | ✅ | `Field(foreign_key="table.column")` |
| Nullable Fields | ✅ | `str \| None` or `Optional[str]` |
| Default Values | ✅ | `Field(default=value)` |
| Indexes | ✅ | `Field(index=True)` — detected and emitted in `--format json`; not drawn in the PlantUML/Mermaid diagram |
| Enums | ✅ | Python `Enum` classes |
| Relationships | ✅ | `Relationship()` |
| Inheritance | ✅ | Mixin classes supported |
| Link Tables | ✅ | Many-to-many detection (structural) |
| Custom Table Names | ✅ | `__tablename__` attribute |
| Exclude Patterns | ✅ | `--exclude` glob on class/table name |
| Key Inference | ✅ | `--infer-keys` for Pydantic/dataclass (`id`, `<x>_id`) |
| File Discovery | ✅ | `--include` globs (`models/` packages, custom filenames) |
| Markdown Embed | ✅ | `--inject` into Markdown between `erdify:start`/`erdify:end` markers |
| SQLModel | ✅ | `Field()` / `Relationship()` |
| SQLAlchemy 2.0 | ✅ | `Mapped[...]` / `mapped_column()` |
| Django ORM | ✅ | `models.Model`, `ForeignKey` / `OneToOneField` / `ManyToManyField` |
| Pydantic | ✅ | `BaseModel` subclasses, nested refs as relationships |
| Dataclass | ✅ | `@dataclass`, nested refs as relationships |
