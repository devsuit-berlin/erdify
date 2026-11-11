"""Relations to Django's user model, the most common external target."""

from django.conf import settings

from django.db import models


class Post(models.Model):
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    editor = models.ForeignKey("auth.User", on_delete=models.SET_NULL, null=True)
