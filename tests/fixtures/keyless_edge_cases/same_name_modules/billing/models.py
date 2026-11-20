"""Same-name classes in different modules (#367): billing's Address."""

from pydantic import BaseModel


class Address(BaseModel):
    street: str
    vat_id: str | None = None


class Invoice(BaseModel):
    number: str
    address: Address
