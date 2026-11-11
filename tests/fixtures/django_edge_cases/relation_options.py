"""Relation options that change keys and nullability."""

from django.db import models


class Product(models.Model):
    sku = models.CharField(max_length=20, unique=True)


class Manual(models.Model):
    product = models.OneToOneField(Product, on_delete=models.CASCADE, null=True)


class Barcode(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, unique=True)


class StockItem(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, to_field="sku")
    replaces = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, db_constraint=False)
