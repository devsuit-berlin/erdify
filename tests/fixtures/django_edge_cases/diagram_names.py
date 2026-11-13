"""Names a diagram grammar can't take as they are (#288).

Model names that are Mermaid keywords and ``db_column`` names with spaces,
punctuation or a leading digit.
"""

from django.db import models


class Class(models.Model):
    title = models.CharField(max_length=50, db_column="Class Title")
    code = models.CharField(max_length=8, unique=True, db_column="1st-code")


class Style(models.Model):
    owner = models.ForeignKey(Class, on_delete=models.CASCADE, db_column="Owner (ID)")
    pk_flag = models.BooleanField(default=False, db_column="PK")


class To(models.Model):
    styles = models.ManyToManyField(Style)
