"""Same-name classes in different modules (#367): shipping's Address, a dataclass."""

from dataclasses import dataclass


@dataclass
class Address:
    city: str
    zip_code: str | None = None
