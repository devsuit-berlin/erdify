"""One-to-many with back_populates; optional and required many-to-one sides.

Two foreign keys to one table, so each side names its column (foreign_keys=).
"""

from typing import List, Optional

from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Customer(Base):
    __tablename__ = "customer"

    id: Mapped[int] = mapped_column(primary_key=True)
    orders: Mapped[List["Order"]] = relationship(
        back_populates="customer", foreign_keys="Order.customer_id"
    )
    referrals: Mapped[list["Order"]] = relationship(
        back_populates="referrer", foreign_keys="Order.referrer_id"
    )


class Order(Base):
    __tablename__ = "order"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customer.id"))
    customer: Mapped["Customer"] = relationship(back_populates="orders", foreign_keys=[customer_id])
    referrer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("customer.id"))
    referrer: Mapped[Optional["Customer"]] = relationship(
        back_populates="referrals", foreign_keys=[referrer_id]
    )
