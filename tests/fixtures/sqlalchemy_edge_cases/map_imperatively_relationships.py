"""Imperative mapping inside a start_mappers() function, with every relationship direction.

Dataclasses mapped imperatively (the "domain model stays plain" pattern),
the table passed as local_table=, a one-to-many with back_populates, a
many-to-one, a one-to-one (uselist=False), a self-referential adjacency list
(remote_side=) and a many-to-many through secondary=.
"""

from dataclasses import dataclass

from sqlalchemy import Column, ForeignKey, Integer, String, Table
from sqlalchemy.orm import registry, relationship

mapper_registry = registry()

customer = Table(
    "customer",
    mapper_registry.metadata,
    Column("id", Integer, primary_key=True),
    Column("email", String(100), nullable=False, unique=True),
)

profile = Table(
    "profile",
    mapper_registry.metadata,
    Column("id", Integer, primary_key=True),
    Column("customer_id", ForeignKey("customer.id"), nullable=False, unique=True),
)

order = Table(
    "purchase_order",
    mapper_registry.metadata,
    Column("id", Integer, primary_key=True),
    Column("customer_id", ForeignKey("customer.id")),
    Column("parent_id", ForeignKey("purchase_order.id")),
)

label = Table(
    "label",
    mapper_registry.metadata,
    Column("id", Integer, primary_key=True),
)

order_label = Table(
    "order_label",
    mapper_registry.metadata,
    Column("order_id", ForeignKey("purchase_order.id"), primary_key=True),
    Column("label_id", ForeignKey("label.id"), primary_key=True),
)


@dataclass
class Customer:
    email: str


@dataclass
class Profile:
    customer_id: int


@dataclass
class Order:
    customer_id: int | None = None


class Label:
    pass


def start_mappers() -> None:
    mapper_registry.map_imperatively(
        Customer,
        customer,
        properties={
            "orders": relationship(Order, back_populates="customer"),
            "profile": relationship(Profile, uselist=False, back_populates="customer"),
        },
    )
    mapper_registry.map_imperatively(
        Profile,
        local_table=profile,
        properties={"customer": relationship(Customer, back_populates="profile")},
    )
    mapper_registry.map_imperatively(
        Order,
        order,
        properties={
            "customer": relationship("Customer", back_populates="orders"),
            "parent": relationship(lambda: Order, remote_side=[order.c.id]),
            "children": relationship(Order, overlaps="parent"),
            "labels": relationship(Label, secondary=order_label),
        },
    )
    mapper_registry.map_imperatively(Label, label)


start_mappers()
