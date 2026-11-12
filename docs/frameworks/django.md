---
description: "Django-specific erdify parsing: table names, foreign key mapping, db_column, field-to-type mapping, TextChoices enums, abstract bases, multi-table inheritance and the user model."
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

A literal `db_column="..."` names the column, on any field including a foreign
key, a primary key and an explicit `parent_link` (`author = ForeignKey(Author,
db_column="writer")` is the column `writer`, not `author_id`). Foreign keys that
reference a renamed column use its new name.

## Table names

Without `Meta.db_table`, the table gets Django's default name,
`<app_label>_<model name>`, where the model name is the class name
lower-cased: `OrderItem` in the app `shop` is `shop_orderitem`. erdify reads the
app label from source, in Django's order:

1. `class Meta: app_label = "..."` on the model.
2. The app's `AppConfig` in `apps.py`: a literal `label`, else the last part of
   a literal `name` (`name = "project.shop"` → `shop`). With several configs,
   the one marked `default = True`.
3. The name of the app package: the directory holding `models.py`, or the
   parent of a `models/` package (`shop/models/order.py` → `shop`).

A model outside the scanned files (a relation target erdify can't see) shows
the lower-cased class name, without a prefix.

## The user model and other contrib models

A custom user model built on Django's `AbstractUser`, or on
`AbstractBaseUser` and `PermissionsMixin`, gets the fields those bases define
(`password`, `last_login`, `is_superuser`, `username`, …, and the `groups` /
`user_permissions` many-to-many) as if their source were scanned. erdify ships
their definitions and adds them when a scanned file imports them from
`django.contrib.auth.models` (or `django.contrib.auth.base_user`).

Relations to models of `django.contrib` reference their real tables, though the
models themselves are not drawn:

| Target | Table |
|---|---|
| `"auth.User"`, `User` imported from `django.contrib.auth.models` | `auth_user` |
| `"auth.Group"` / `Group`, `"auth.Permission"` / `Permission` | `auth_group`, `auth_permission` |
| `"contenttypes.ContentType"` / `ContentType` | `django_content_type` |
| `settings.AUTH_USER_MODEL`, `get_user_model()` | the custom user model, see below |

`AUTH_USER_MODEL` is set in `settings.py`, which erdify doesn't read. It
resolves to the one scanned concrete model built on `AbstractBaseUser` (also via
`AbstractUser`); with none or several, to Django's default `auth_user`.

## Inheritance

Inheritance follows Django's three model inheritance styles:

| Base | Result |
|---|---|
| Abstract base (`class Meta: abstract = True`) | Not drawn; its fields are copied into each subclass. |
| Concrete model (**multi-table inheritance**) | The subclass gets its own table with only its own fields (plus those of its abstract bases) and a `<parent>_ptr_id` column: a one-to-one link to the parent, drawn 1:1. The parent's fields stay on the parent. |
| Proxy model (`class Meta: proxy = True`) | Not drawn: a proxy has no table. A relation to a proxy, or a subclass of one, points at the model the proxy stands for. |

```python
class Place(models.Model):
    name = models.CharField(max_length=50)


class Restaurant(Place):             # place_ptr_id PK,FK -> <app>_place.id
    serves_pizza = models.BooleanField()
```

As in Django:

- The link is named after the parent's lower-cased class name (`OrderItem` →
  `orderitem_ptr_id`).
- It is the subclass's primary key unless the subclass declares one; with
  several concrete parents, only the first link is the primary key and the
  others are unique one-to-one columns. The primary key is listed first.
- An explicit `OneToOneField(Place, parent_link=True)`, in the subclass or one
  of its abstract bases, replaces the implicit link.
- An abstract base that subclasses a concrete model passes its link on to the
  models built from it.
- A foreign key to the subclass references its link column; a `to_field=`
  naming one of the parent's fields references the parent's table.

## Relationship targets

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

`models.TextChoices` / `models.IntegerChoices` classes (also through a project's
own choices base) are rendered as enums,
and a field that references one via `choices=Status.choices` (or
`choices=Status`) is linked to that enum. Inline `choices=[("a", "A"), …]`
tuples are anonymous and not rendered as enums.
