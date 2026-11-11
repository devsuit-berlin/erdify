"""Choices nested in the model (Django's documented idiom) and a plain enum.Enum."""

import enum

from django.db import models


class Channel(enum.Enum):
    EMAIL = "email"
    SMS = "sms"


class Student(models.Model):
    class YearInSchool(models.TextChoices):
        FRESHMAN = "FR", "Freshman"
        SENIOR = "SR", "Senior"

    year = models.CharField(max_length=2, choices=YearInSchool.choices)
    channel = models.CharField(max_length=5, choices=[(c.value, c.name) for c in Channel])
