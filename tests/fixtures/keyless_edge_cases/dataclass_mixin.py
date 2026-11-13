"""A plain (undecorated) mixin's annotations are not dataclass fields."""

from dataclasses import dataclass


class AuditMixin:
    created_by: str


@dataclass
class Invoice(AuditMixin):
    id: int


class Plain:
    value: bytes


@dataclass
class Base:
    # Nullable, unlike Plain's: the harness sees which one wins.
    value: int | None = None


@dataclass
class Child(Plain, Base):
    # value comes from Base: Plain is not a dataclass.
    id: int = 0
