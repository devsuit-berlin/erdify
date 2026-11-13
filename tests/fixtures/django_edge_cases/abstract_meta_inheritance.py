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


class Filed(models.Model):
    class Meta:
        abstract = True
        db_table = "filed_memo"


class Memo(Filed):
    """Its own Meta subclasses the base's, so db_table is inherited."""

    class Meta(Filed.Meta):
        ordering = ["id"]


class Archived(models.Model):
    class Meta:
        abstract = True
        db_table = "archived_note"


class Note(Archived):
    """Its own Meta does not subclass the base's: the default table name."""

    class Meta:
        ordering = ["id"]


class Labelled(models.Model):
    class Meta:
        abstract = True
        app_label = "core"


class Tag(Labelled):
    """app_label is inherited too, and decides the default table name."""
