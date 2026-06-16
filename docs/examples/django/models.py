"""Framework comparison schema - Django ORM.

The same User/Order schema is expressed in docs/examples/{sqlmodel,sqlalchemy,
django,pydantic,dataclass} and produces an identical ERD. Django needs no
--infer-keys: it has an implicit `id` primary key, and field types are mapped to
Python types (CharField/EmailField -> str, FloatField -> float).
"""

from django.db import models


class User(models.Model):
    name = models.CharField(max_length=100)
    email = models.EmailField()

    class Meta:
        db_table = "user"


class Order(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    total = models.FloatField()

    class Meta:
        db_table = "order"
