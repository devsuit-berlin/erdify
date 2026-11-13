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


class Site(models.Model):
    pass


class UUIDKeyed(models.Model):
    id = models.UUIDField(primary_key=True)

    class Meta:
        abstract = True


class Kiosk(Site, UUIDKeyed):
    """Site's implicit id takes the name: UUIDKeyed.id is not copied, site_ptr is the PK."""


class KioskOrder(models.Model):
    kiosk = models.ForeignKey(Kiosk, on_delete=models.CASCADE)
