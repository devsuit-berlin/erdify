"""Core Table(...) objects next to mapped classes: association, payload and lookup tables."""

from sqlalchemy import Column, ForeignKey, Integer, String, Table
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "account"

    id: Mapped[int] = mapped_column(primary_key=True)
    country_code: Mapped[str] = mapped_column(ForeignKey("country.code"))


account_role = Table(
    "account_role",
    Base.metadata,
    Column("account_id", ForeignKey("account.id"), primary_key=True),
    Column("role_id", ForeignKey("role.id"), primary_key=True),
)

role = Table(
    "role",
    Base.metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(50), nullable=False, unique=True),
)

country = Table(
    "country",
    Base.metadata,
    Column("code", String(2), primary_key=True),
    Column("name", String(100), nullable=False),
)

audit_log = Table(
    "audit_log",
    Base.metadata,
    Column("id", Integer, primary_key=True),
    Column("account_id", ForeignKey("account.id"), nullable=True),
    Column("message", String(200), nullable=False),
)
