"""An __abstract__ declarative base with shared columns."""

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Entity(Base):
    __abstract__ = True

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(default=1)


class Invoice(Entity):
    __tablename__ = "invoice"

    number: Mapped[str] = mapped_column(unique=True)
