"""A project-defined Field subclass is still a column."""

from django.db import models


class MoneyField(models.DecimalField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("max_digits", 12)
        kwargs.setdefault("decimal_places", 2)
        super().__init__(*args, **kwargs)


class Invoice(models.Model):
    total = MoneyField()
    tax = MoneyField(null=True)
