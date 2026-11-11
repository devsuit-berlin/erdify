"""WriteOnlyMapped and DynamicMapped collections."""

from sqlalchemy import ForeignKey
from sqlalchemy.orm import (
    DeclarativeBase,
    DynamicMapped,
    Mapped,
    WriteOnlyMapped,
    mapped_column,
    relationship,
)


class Base(DeclarativeBase):
    pass


class Feed(Base):
    __tablename__ = "feed"

    id: Mapped[int] = mapped_column(primary_key=True)
    entries: WriteOnlyMapped["Entry"] = relationship(back_populates="feed")
    tags: DynamicMapped["Tag"] = relationship()


class Entry(Base):
    __tablename__ = "entry"

    id: Mapped[int] = mapped_column(primary_key=True)
    feed_id: Mapped[int] = mapped_column(ForeignKey("feed.id"))
    feed: Mapped["Feed"] = relationship(back_populates="entries")


class Tag(Base):
    __tablename__ = "tag"

    id: Mapped[int] = mapped_column(primary_key=True)
    feed_id: Mapped[int | None] = mapped_column(ForeignKey("feed.id"))
