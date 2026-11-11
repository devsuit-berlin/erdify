"""Python Enum columns: every enum.Enum subclass, also through a project base (#296)."""

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


class Color(enum.StrEnum):
    RED = "red"
    BLUE = "blue"


class Permission(enum.Flag):
    READ = 1
    WRITE = 2


class Level(enum.IntFlag):
    ONE = 1
    TWO = 2


class LabeledEnum(str, enum.Enum):
    """A project enum base without members."""


class Kind(LabeledEnum):
    BUG = "bug"
    TASK = "task"


class Ticket(Base):
    __tablename__ = "ticket"

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[Status]
    priority: Mapped[Priority | None] = mapped_column(Enum(Priority))
    color: Mapped[Color]
    permission: Mapped[Permission]
    level: Mapped[Level]
    kind: Mapped[Kind]
