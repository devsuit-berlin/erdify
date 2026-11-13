"""Fields on a plain (non-Model) mixin are no columns in Django (#280)."""

import uuid
from typing import Generic, TypeVar

from django.db import models

T = TypeVar("T")


class TreeMixin:
    parent = models.ForeignKey("self", null=True, on_delete=models.CASCADE)

    def describe(self) -> str:
        return "node"


class Node(TreeMixin, models.Model):
    """Has only the implicit id: parent stays a plain class attribute."""


class Described(models.Model):
    describe = models.CharField(max_length=50)
    title = models.CharField(max_length=50)

    class Meta:
        abstract = True


class Page(TreeMixin, Described):
    """The mixin's describe() takes the name before Described's field is copied."""


class Mixin:
    pass


class Unknown(Mixin, object):
    pass


class Article(Unknown, models.Model):
    """A scanned plain base chain, through object, is known not to be a model."""

    body = models.TextField()


class UUIDModel(models.Model):
    id = models.UUIDField(primary_key=True)

    class Meta:
        abstract = True


class Order(UUIDModel):
    """A bare annotation binds no name: the UUID primary key is still inherited."""

    id: uuid.UUID


class Line(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE)


class HasTitle:
    title: str


class Story(HasTitle, Described):
    """A typing-only mixin doesn't block Described's title either."""


class Typed(Generic[T]):
    label = models.CharField(max_length=10)


class Badge(Typed[str], models.Model):
    """A Generic mixin is no model: its field is no column."""
