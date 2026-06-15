"""SQLAlchemy many-to-many via relationship(secondary=...) - regression fixture.

The SQLAlchemy analogue of SQLModel's link_model= is relationship(secondary=...).
When the association is a mapped link-table class, the M:N is already drawn
through that link table; the declared relationship must not add a direct edge.
"""

from typing import List

from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base - not a table itself."""


class Post(Base):
    """Post entity."""

    __tablename__ = "post"

    id: Mapped[int] = mapped_column(primary_key=True)
    tags: Mapped[List["Tag"]] = relationship(secondary="post_tag_link", back_populates="posts")


class Tag(Base):
    """Tag entity."""

    __tablename__ = "tag"

    id: Mapped[int] = mapped_column(primary_key=True)
    posts: Mapped[List["Post"]] = relationship(secondary="post_tag_link", back_populates="tags")


class PostTagLink(Base):
    """Link table for the post <-> tag many-to-many."""

    __tablename__ = "post_tag_link"

    post_id: Mapped[int] = mapped_column(ForeignKey("post.id"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tag.id"), primary_key=True)
