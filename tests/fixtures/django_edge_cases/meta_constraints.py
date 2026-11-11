"""Uniqueness declared in Meta rather than on the field."""

from django.db import models


class Account(models.Model):
    email = models.CharField(max_length=100)
    tenant = models.IntegerField()
    slug = models.SlugField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["email"], name="uniq_email")]
        unique_together = [("tenant", "slug")]
        indexes = [models.Index(fields=["slug"])]
