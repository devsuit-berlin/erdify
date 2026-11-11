"""Classic declarative Column() attributes, also mixed with Mapped[] members."""

from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Legacy(Base):
    __tablename__ = "legacy"

    id = Column(Integer, primary_key=True)
    name = Column(String(50), nullable=False)


class Mixed(Base):
    __tablename__ = "mixed"

    id: Mapped[int] = mapped_column(primary_key=True)
    legacy_id = Column(Integer, ForeignKey("legacy.id"))
