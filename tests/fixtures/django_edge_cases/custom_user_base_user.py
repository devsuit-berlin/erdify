"""A user model on AbstractBaseUser + PermissionsMixin, and FKs to contrib by import."""

from django.contrib.auth.models import AbstractBaseUser, Group, PermissionsMixin
from django.db import models


class Account(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True)
    team = models.ForeignKey(Group, on_delete=models.SET_NULL, null=True)
