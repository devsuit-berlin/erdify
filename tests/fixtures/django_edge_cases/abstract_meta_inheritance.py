"""An abstract base's Meta (db_table, related_name placeholders) is inherited."""

from django.db import models


class Owner(models.Model):
    pass


class Audited(models.Model):
    owner = models.ForeignKey(
        Owner, on_delete=models.CASCADE, related_name="%(app_label)s_%(class)s_set"
    )

    class Meta:
        abstract = True
        db_table = "audited_thing"


class Document(Audited):
    pass


class Report(Audited):
    class Meta(Audited.Meta):
        db_table = "report"
