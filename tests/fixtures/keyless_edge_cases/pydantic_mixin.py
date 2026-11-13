"""A plain (non-BaseModel) mixin's annotations become fields of the Pydantic model."""

from pydantic import BaseModel


class AuditMixin:
    created_by: str


class Invoice(BaseModel, AuditMixin):
    id: int


class Base(BaseModel):
    created_by: int


class Overridden(AuditMixin, Base):
    # The model base's field wins over the mixin's earlier annotation.
    id: int
