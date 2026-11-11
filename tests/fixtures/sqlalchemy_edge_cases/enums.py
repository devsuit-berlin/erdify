"""Python Enum columns."""

import enum

from sqlalchemy import Enum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Status(enum.Enum):
    DRAFT = "draft"
    PUBLISHED = "published"


class Priority(enum.IntEnum):
    LOW = 1
    HIGH = 2


class Ticket(Base):
    __tablename__ = "ticket"

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[Status]
    priority: Mapped[Priority | None] = mapped_column(Enum(Priority))
