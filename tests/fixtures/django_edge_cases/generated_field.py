"""GeneratedField (Django 5.0) is a real column; db_default is just a default."""

from django.db.models import F

from django.db import models


class Rectangle(models.Model):
    width = models.IntegerField(db_default=1)
    height = models.IntegerField()
    area = models.GeneratedField(
        expression=F("width") * F("height"),
        output_field=models.BigIntegerField(),
        db_persist=True,
    )
