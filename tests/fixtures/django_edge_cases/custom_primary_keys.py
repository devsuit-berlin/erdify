"""Explicit primary keys of different field types."""

from django.db import models


class Token(models.Model):
    key = models.UUIDField(primary_key=True)


class Counter(models.Model):
    id = models.BigAutoField(primary_key=True)


class Flag(models.Model):
    id = models.SmallAutoField(primary_key=True)
    token = models.ForeignKey(Token, on_delete=models.CASCADE)
    counter = models.ForeignKey(Counter, on_delete=models.CASCADE)


class Country(models.Model):
    code = models.CharField(max_length=2, primary_key=True)


class City(models.Model):
    country = models.ForeignKey(Country, on_delete=models.CASCADE)
