"""ManyToManyField options: db_table, asymmetric self, through_fields."""

from django.db import models


class Person(models.Model):
    following = models.ManyToManyField("self", symmetrical=False, related_name="followers")
    friends = models.ManyToManyField("self")


class Tag(models.Model):
    pass


class Article(models.Model):
    tags = models.ManyToManyField(Tag, db_table="article_tag_map")


class Team(models.Model):
    members = models.ManyToManyField(
        Person, through="Membership", through_fields=("team", "person")
    )


class Membership(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    person = models.ForeignKey(Person, on_delete=models.CASCADE)
    inviter = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="membership_invites")
