"""References to both Address classes, through different import forms."""

from __future__ import annotations

from pydantic import BaseModel

import shipping.models
from billing import models as billing_models
from billing.models import Address as BillingAddress
from billing.models import Invoice

__all__ = ["Order", "Return"]


class Order(BaseModel):
    billing_address: BillingAddress
    shipping_addresses: list[shipping.models.Address]
    invoice: "Invoice | None" = None
    billing_copy: billing_models.Address | None = None


class Return(BaseModel):
    order: Order
    pickup: "shipping.models.Address | None" = None
