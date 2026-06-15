"""SQLModel many-to-many via Relationship(link_model=...) - regression fixture.

A Relationship that carries link_model= declares an M:N association already
expressed by the link table. It must NOT also produce a direct (mis-cardinalized)
edge between the two endpoints.
"""

import uuid

from sqlmodel import Field, Relationship, SQLModel


class RestaurantStaffLink(SQLModel, table=True):
    """Link table for the restaurant <-> staff many-to-many."""

    restaurant_id: uuid.UUID = Field(foreign_key="restaurant.id", primary_key=True)
    staff_id: uuid.UUID = Field(foreign_key="staff.id", primary_key=True)


class Restaurant(SQLModel, table=True):
    """Restaurant entity."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    staff: list["Staff"] = Relationship(
        back_populates="restaurants", link_model=RestaurantStaffLink
    )


class Staff(SQLModel, table=True):
    """Staff entity."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    restaurants: list[Restaurant] = Relationship(
        back_populates="staff", link_model=RestaurantStaffLink
    )
