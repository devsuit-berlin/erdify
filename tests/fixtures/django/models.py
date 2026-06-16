"""Django ORM models fixture (#36).

Covers the constructs erdify must translate: abstract base inheritance,
column field types, implicit/explicit primary keys, ForeignKey (N:1),
OneToOneField (1:1), ManyToManyField (plain and via through=), Meta.db_table
overrides, and the "self" self-reference.
"""

from django.db import models


class TimestampedModel(models.Model):
    """Abstract base - its fields are inherited but it is not drawn."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Author(TimestampedModel):
    """Concrete model inheriting the abstract base; gets an implicit id PK."""

    name = models.CharField(max_length=100)
    bio = models.TextField()


class Profile(models.Model):
    """OneToOne with Author (1:1). ``preferences`` exercises the type fallback."""

    author = models.OneToOneField(Author, on_delete=models.CASCADE)
    website = models.URLField()
    preferences = models.JSONField(default=dict)


class Tag(models.Model):
    label = models.CharField(max_length=50)


class Post(TimestampedModel):
    """ForeignKey (N:1), plain ManyToManyField, and a db_table override."""

    title = models.CharField(max_length=200)
    author = models.ForeignKey(Author, on_delete=models.CASCADE)
    tags = models.ManyToManyField("Tag")

    class Meta:
        db_table = "blog_post"


class Group(models.Model):
    """ManyToManyField via an explicit through= model."""

    name = models.CharField(max_length=100)
    members = models.ManyToManyField(Author, through="Membership")


class Membership(models.Model):
    """Through model for Group <-> Author; a full entity with extra data."""

    author = models.ForeignKey(Author, on_delete=models.CASCADE)
    group = models.ForeignKey(Group, on_delete=models.CASCADE)
    role = models.CharField(max_length=50)


class Category(models.Model):
    """Self-referential ForeignKey ("self")."""

    name = models.CharField(max_length=100)
    parent = models.ForeignKey("self", on_delete=models.CASCADE, null=True)
