"""Sample SQLModel models for testing - basic e-commerce schema."""

from enum import Enum
from typing import TYPE_CHECKING, List

from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    pass


class UserRole(Enum):
    """User role enumeration."""

    ADMIN = "admin"
    USER = "user"
    GUEST = "guest"


class OrderStatus(Enum):
    """Order status enumeration."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class User(SQLModel, table=True):
    """User entity."""

    __tablename__: str = "user"

    id: int = Field(primary_key=True)
    name: str
    email: str = Field(index=True)
    role: UserRole = Field(default=UserRole.USER)
    is_active: bool = Field(default=True)
    bio: str | None = None

    orders: List["Order"] = Relationship(back_populates="user")


class Product(SQLModel, table=True):
    """Product entity."""

    __tablename__: str = "product"

    id: int = Field(primary_key=True)
    name: str
    price: float
    description: str | None = None
    in_stock: bool = Field(default=True)


class Order(SQLModel, table=True):
    """Order entity."""

    __tablename__: str = "order"

    id: int = Field(primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    status: OrderStatus = Field(default=OrderStatus.PENDING)
    total: float
    notes: str | None = None

    user: "User" = Relationship(back_populates="orders")
    items: List["OrderItem"] = Relationship(back_populates="order")


class OrderItem(SQLModel, table=True):
    """Order item entity (order line)."""

    __tablename__: str = "order_item"

    id: int = Field(primary_key=True)
    order_id: int = Field(foreign_key="order.id")
    product_id: int = Field(foreign_key="product.id")
    quantity: int
    unit_price: float

    order: "Order" = Relationship(back_populates="items")


class UserProductLink(SQLModel, table=True):
    """Link table for user favorites (many-to-many)."""

    __tablename__: str = "user_product_link"

    user_id: int = Field(foreign_key="user.id", primary_key=True)
    product_id: int = Field(foreign_key="product.id", primary_key=True)
