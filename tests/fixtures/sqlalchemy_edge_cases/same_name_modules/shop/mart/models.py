"""Same-name classes in different modules (#367): mart's Customer refers to core's."""

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shop.base import Base
from shop.core.models import Customer as CoreCustomer


class Customer(Base):
    __tablename__ = "customer"
    __table_args__ = {"schema": "mart"}

    id: Mapped[int] = mapped_column(primary_key=True)
    core_id: Mapped[int | None] = mapped_column(ForeignKey("core.customer.id"))
    core: Mapped[CoreCustomer | None] = relationship()


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = {"schema": "mart"}

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("mart.customer.id"))
    # Two mapped classes are called Customer: SQLAlchemy needs the module path,
    # which it resolves in its class registry (not a Python name here).
    customer: Mapped["shop.mart.models.Customer"] = relationship()  # noqa: F821
