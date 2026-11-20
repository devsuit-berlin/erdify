"""Same-name models in two apps (#367): shipping's Profile."""

from django.db import models


class Profile(models.Model):
    street = models.CharField(max_length=100)


class Parcel(models.Model):
    # A class reference: this module's Profile.
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE)
    payers = models.ManyToManyField("billing.Profile", related_name="parcels")
