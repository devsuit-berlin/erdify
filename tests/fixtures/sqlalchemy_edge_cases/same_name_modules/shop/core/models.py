"""Same-name classes in different modules (#367): core's Customer."""

from sqlalchemy.orm import Mapped, mapped_column

from shop.base import Base


class Customer(Base):
    __tablename__ = "customer"
    __table_args__ = {"schema": "core"}

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str]
