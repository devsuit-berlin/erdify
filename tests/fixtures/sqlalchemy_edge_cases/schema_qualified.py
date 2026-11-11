"""Tables in a database schema: __table_args__ = {"schema": ...}."""

from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenant"
    __table_args__ = {"schema": "core"}

    id: Mapped[int] = mapped_column(primary_key=True)


class Invoice(Base):
    __tablename__ = "invoice"
    __table_args__ = {"schema": "billing"}

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("core.tenant.id"))
