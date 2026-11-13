"""A plain (non-BaseModel) mixin's annotations become fields of the Pydantic model."""

from pydantic import BaseModel


class AuditMixin:
    created_by: str


class Invoice(BaseModel, AuditMixin):
    id: int


class Base(BaseModel):
    # Nullable, unlike the mixin's: the harness sees which one wins.
    created_by: int | None = None


class Overridden(AuditMixin, Base):
    # The model base's field wins over the mixin's earlier annotation.
    id: int


class DefaultingMixin:
    created_by: str = "system"


class Defaulted(DefaultingMixin, Base):
    # A default on a plain base makes Pydantic read the first annotation in
    # the MRO (the mixin's), not Base's field.
    id: int


class Late(Base, DefaultingMixin):
    # Base comes first in the MRO: its annotation is the first one.
    id: int
