"""Same-name models in two apps (#367): billing's Profile."""

from django.db import models


class Profile(models.Model):
    iban = models.CharField(max_length=34)


class Invoice(models.Model):
    # A bare name: the model of this app, as Django resolves it.
    profile = models.ForeignKey("Profile", on_delete=models.CASCADE)
    # The other app's model, by app label (any case).
    ship_to = models.ForeignKey(
        "shipping.profile", on_delete=models.CASCADE, related_name="billed_invoices"
    )
