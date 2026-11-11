"""Django 5.2 CompositePrimaryKey: no implicit id, both columns are the key."""

from django.db import models


class Order(models.Model):
    pass


class Product(models.Model):
    pass


class OrderLine(models.Model):
    pk = models.CompositePrimaryKey("order_id", "product_id")
    order = models.ForeignKey(Order, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.IntegerField()
