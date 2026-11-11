"""The ways a model points at Django's default user model and other contrib models."""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission, User
from django.db import models


class Note(models.Model):
    author = models.ForeignKey(User, on_delete=models.CASCADE)
    reviewer = models.ForeignKey("auth.user", on_delete=models.CASCADE, related_name="+")
    owner = models.ForeignKey(get_user_model(), on_delete=models.CASCADE, related_name="+")
    grants = models.ManyToManyField(Permission)
