"""Choices built on a project's own choices base are enums (#296)."""

from django.db import models


class LabeledChoices(models.TextChoices):
    """A project choices base without members."""


class Status(LabeledChoices):
    OPEN = "open"
    CLOSED = "closed"


class Ticket(models.Model):
    status = models.CharField(max_length=6, choices=Status.choices)
