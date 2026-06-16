"""SQLAlchemy M:N via relationship(secondary=Table(...)) - Core Table variant (#34).

Unlike the mapped link-table *class* case (see m2m_secondary), here the
association table is a module-level Core ``Table(...)`` assignment. erdify must
still model that table as a link entity so the M:N is drawn through it, rather
than dropping the relationship (or drawing a mis-cardinalized direct edge).
"""

from typing import List

from sqlalchemy import Column, ForeignKey, Table
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base - not a table itself."""


post_tag = Table(
    "post_tag",
    Base.metadata,
    Column("post_id", ForeignKey("post.id"), primary_key=True),
    Column("tag_id", ForeignKey("tag.id"), primary_key=True),
)


class Post(Base):
    """Post entity."""

    __tablename__ = "post"

    id: Mapped[int] = mapped_column(primary_key=True)
    tags: Mapped[List["Tag"]] = relationship(secondary=post_tag, back_populates="posts")


class Tag(Base):
    """Tag entity."""

    __tablename__ = "tag"

    id: Mapped[int] = mapped_column(primary_key=True)
    posts: Mapped[List["Post"]] = relationship(secondary=post_tag, back_populates="tags")
