"""A custom user model built on AbstractUser (fields come from Django)."""

from django.contrib.auth.models import AbstractUser

from django.db import models


class Member(AbstractUser):
    nickname = models.CharField(max_length=30)
