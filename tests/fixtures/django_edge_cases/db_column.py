"""Custom column names via db_column, on a plain field and on a foreign key."""

from django.db import models


class Author(models.Model):
    name = models.CharField(max_length=50, db_column="author_name")


class Book(models.Model):
    author = models.ForeignKey(Author, on_delete=models.CASCADE, db_column="writer")
    isbn = models.CharField(max_length=13, db_column="ISBN", unique=True)
