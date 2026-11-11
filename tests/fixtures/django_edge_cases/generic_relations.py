"""contenttypes GenericForeignKey: two real columns, the GFK itself is virtual."""

from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType

from django.db import models


class Comment(models.Model):
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    target = GenericForeignKey("content_type", "object_id")


class Photo(models.Model):
    comments = GenericRelation(Comment)
