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


class Group(models.Model):
    pass


class Person(models.Model):
    pass


class Membership(models.Model):
    """Field names instead of attnames; no payload, so a link table."""

    pk = models.CompositePrimaryKey("group", "person")
    group = models.ForeignKey(Group, on_delete=models.CASCADE)
    person = models.ForeignKey(Person, on_delete=models.CASCADE)


class Invoice(models.Model):
    pass


class LineBase(models.Model):
    """A composite key inherited from an abstract base."""

    pk = models.CompositePrimaryKey("invoice_id", "position")
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE)
    position = models.PositiveIntegerField()

    class Meta:
        abstract = True


class InvoiceLine(LineBase):
    amount = models.DecimalField(max_digits=10, decimal_places=2)


class Tenant(models.Model):
    pass


class Seat(models.Model):
    """A member of the key keeps its own UNIQUE (a one-to-one is still unique)."""

    pk = models.CompositePrimaryKey("person", "tenant")
    person = models.OneToOneField(Person, on_delete=models.CASCADE)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
