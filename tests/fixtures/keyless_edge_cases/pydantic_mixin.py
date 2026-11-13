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
