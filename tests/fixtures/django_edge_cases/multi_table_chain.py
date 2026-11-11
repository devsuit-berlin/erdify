"""Multi-table inheritance over three levels and a proxy at the end."""

from django.db import models


class Place(models.Model):
    name = models.CharField(max_length=50)


class Restaurant(Place):
    serves_pizza = models.BooleanField(default=False)


class Pizzeria(Restaurant):
    oven_count = models.IntegerField()


class FancyPizzeria(Pizzeria):
    class Meta:
        proxy = True


class Review(models.Model):
    venue = models.ForeignKey(FancyPizzeria, on_delete=models.CASCADE)
