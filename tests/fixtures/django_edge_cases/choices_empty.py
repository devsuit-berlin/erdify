"""A Choices enum with an __empty__ label."""

from django.db import models


class Size(models.TextChoices):
    SMALL = "S", "Small"
    LARGE = "L", "Large"
    __empty__ = "(Unknown)"


class Shirt(models.Model):
    size = models.CharField(max_length=1, choices=Size.choices, blank=True)
