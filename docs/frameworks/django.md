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
    tags = models.ManyToManyField("Tag")                            # M:N
    profile = models.OneToOneField("Profile", on_delete=models.CASCADE)  # 1:1

    class Meta:
        db_table = "catalog_book"
```

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
