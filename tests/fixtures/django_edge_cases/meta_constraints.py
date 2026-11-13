"""Uniqueness declared in Meta rather than on the field."""

from django.db import models
from django.db.models.functions import Lower


class Account(models.Model):
    email = models.CharField(max_length=100)
    tenant = models.IntegerField()
    slug = models.SlugField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["email"], name="uniq_email")]
        unique_together = [("tenant", "slug")]
        indexes = [models.Index(fields=["slug"])]


class Owner(models.Model):
    pass


class Membership(models.Model):
    """Constraint fields may be a field name or an attname."""

    owner = models.ForeignKey(Owner, on_delete=models.CASCADE)
    handle = models.CharField(max_length=50)
    code = models.CharField(max_length=10)
    nick = models.CharField(max_length=50)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["owner"], name="uniq_owner"),
            models.UniqueConstraint(
                fields=["code"], condition=models.Q(code__gt=""), name="uniq_code_partial"
            ),
            models.UniqueConstraint(Lower("handle"), name="uniq_handle_lower"),
        ]


class Profile(models.Model):
    """A flat unique_together tuple is one group; the attname form."""

    owner = models.ForeignKey(Owner, on_delete=models.CASCADE)

    class Meta:
        unique_together = ("owner_id",)


class Coded(models.Model):
    code = models.CharField(max_length=10)

    class Meta:
        abstract = True
        constraints = [models.UniqueConstraint(fields=["code"], name="%(class)s_uniq_code")]


class Voucher(Coded):
    """Constraints of an abstract base's Meta are inherited."""
