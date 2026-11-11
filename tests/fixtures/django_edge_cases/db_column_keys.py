"""db_column on keys: FKs to a renamed PK or to_field, inherited and parent-link columns."""

from django.db import models


class Customer(models.Model):
    number = models.IntegerField(primary_key=True, db_column="CUST_NO")
    code = models.CharField(max_length=8, unique=True, db_column="CUST_CODE")


class Audited(models.Model):
    created_by = models.ForeignKey(
        Customer, on_delete=models.CASCADE, db_column="CREATED_BY", related_name="+"
    )

    class Meta:
        abstract = True


class Order(Audited):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    by_code = models.ForeignKey(
        Customer, on_delete=models.CASCADE, to_field="code", related_name="+"
    )


class Place(models.Model):
    name = models.CharField(max_length=50, db_column="NAME")


class Restaurant(Place):
    place = models.OneToOneField(
        Place, on_delete=models.CASCADE, parent_link=True, db_column="PLACE_REF"
    )


class Review(models.Model):
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE)
