"""managed = False models are still tables (owned by someone else)."""

from django.db import models


class LegacyCustomer(models.Model):
    name = models.CharField(max_length=50)

    class Meta:
        managed = False
        db_table = "crm_customer"


class Ticket(models.Model):
    customer = models.ForeignKey(LegacyCustomer, on_delete=models.DO_NOTHING)
