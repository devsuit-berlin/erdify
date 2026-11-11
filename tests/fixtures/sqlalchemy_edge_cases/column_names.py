"""Explicit column names: mapped_column("name") and mapped_column(name=...)."""

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "account"

    id: Mapped[int] = mapped_column("account_id", primary_key=True)
    email: Mapped[str] = mapped_column("email_address", String(200), unique=True)
    display: Mapped[str | None] = mapped_column(name="display_name")


class Profile(Base):
    __tablename__ = "profile"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[int] = mapped_column("owner_id", ForeignKey("account.account_id"))
