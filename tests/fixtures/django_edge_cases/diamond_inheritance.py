"""Diamond abstract inheritance: Django keeps the first copy along the MRO (#272)."""

from django.db import models


class Account(models.Model):
    pass


class Other(models.Model):
    pass


class Root(models.Model):
    owner = models.OneToOneField(Account, on_delete=models.CASCADE)

    class Meta:
        abstract = True


class Left(Root):
    class Meta:
        abstract = True


class Right(Root):
    owner = models.OneToOneField(Other, on_delete=models.CASCADE, primary_key=True)

    class Meta:
        abstract = True


class Settings(Left, Right):
    """Left's copy of Root.owner wins, though Python would find Right.owner."""


class Removed(Root):
    owner = None

    class Meta:
        abstract = True


class Profile(Removed, Right):
    """Removed's owner = None blocks only Removed's copy: Root comes after Right."""
