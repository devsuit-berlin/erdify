---
description: "Django-specific erdify parsing: foreign key mapping, field-to-type mapping, TextChoices enums, abstract bases and Meta.db_table."
---

# Django ORM

erdify parses Django models from source — no Django runtime, settings, or app registry required.

A `models.Model` subclass becomes an entity; abstract bases
(`class Meta: abstract = True`) are inherited but not drawn, and a `class Meta:
db_table = "..."` overrides the table name.

```python
from django.db import models


class Author(models.Model):          # implicit `id` primary key (int)
    name = models.CharField(max_length=100)


class Book(models.Model):
    title = models.CharField(max_length=200)
    author = models.ForeignKey(Author, on_delete=models.CASCADE)   # N:1
    editor = models.ForeignKey(Author, null=True, on_delete=models.SET_NULL,
                               related_name="+")                     # N:0..1
    tags = models.ManyToManyField("Tag")                            # M:N
    profile = models.OneToOneField("Profile", on_delete=models.CASCADE)  # 1:1

    class Meta:
        db_table = "catalog_book"
```

`ForeignKey` and `OneToOneField` are modeled as the `<name>_id` column they
create in the database. A `ForeignKey(null=True)` is drawn optional on the
referenced side (`}o--o|`). A `OneToOneField` is a unique foreign key, so it is
marked `UK` and drawn 1:1 like `ForeignKey(unique=True)`: `|o--||`, or
`|o--o|` with `null=True`. A `unique=True` column is marked `UK`. A
`ForeignKey(primary_key=True)` or `OneToOneField(primary_key=True)` (shared
primary key) makes `<name>_id` the table's primary key (no implicit `id` is
added) and is drawn 1:1 as well.

The column references the target's primary key, including one inherited from
an abstract base, or the `to_field=` column, and takes that column's type
(`foreign_table` in [JSON output](../usage/output-formats.md#json)). A target
outside the parsed files is assumed to reference its implicit `id` (or the
`to_field=` column), typed as Django's default auto field.

Relationship targets are resolved by class name, including `"self"` and
`"app.Model"` string references. A `ManyToManyField(through=LinkModel)` is drawn
through the link model's own foreign keys (no spurious direct edge), exactly like
SQLAlchemy `secondary=`.

By default Django field types are mapped to readable Python types
(`CharField` → `str`, `IntegerField`/`AutoField` → `int`, `DateTimeField` →
`datetime`, …) so mixed-source diagrams stay consistent. Ambiguous or unknown
fields (`JSONField`, `FileField`, custom/third-party fields) keep their Django
name rather than fake a type. Pass `--django-raw-types` to show the original
Django field names everywhere instead.

`models.TextChoices` / `models.IntegerChoices` classes are rendered as enums,
and a field that references one via `choices=Status.choices` (or
`choices=Status`) is linked to that enum. Inline `choices=[("a", "A"), …]`
tuples are anonymous and not rendered as enums.
