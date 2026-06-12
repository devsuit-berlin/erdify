"""Sample SQLAlchemy 2.0 (Mapped/mapped_column) models for testing - blog schema."""

from enum import Enum
from typing import List, Optional

from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base - not a table itself."""


class TimestampMixin:
    """Mixin with timestamp columns - no __tablename__, not a table."""

    created_at: Mapped[str] = mapped_column()
    updated_at: Mapped[str] = mapped_column()


class PostStatus(Enum):
    """Post status enumeration."""

    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class Author(Base, TimestampMixin):
    """Author entity."""

    __tablename__ = "author"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column()
    email: Mapped[str] = mapped_column(index=True)
    bio: Mapped[Optional[str]] = mapped_column(default=None)
    is_active: Mapped[bool] = mapped_column(default=True)

    posts: Mapped[List["Post"]] = relationship(back_populates="author")


class Post(Base, TimestampMixin):
    """Post entity."""

    __tablename__ = "post"

    id: Mapped[int] = mapped_column(primary_key=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("author.id"))
    title: Mapped[str] = mapped_column()
    status: Mapped[PostStatus] = mapped_column(default=PostStatus.DRAFT)
    summary: Mapped[str | None] = mapped_column(default=None)

    author: Mapped["Author"] = relationship(back_populates="posts")


class Tag(Base):
    """Tag entity."""

    __tablename__ = "tag"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column()


class PostTagLink(Base):
    """Link table for post tags (many-to-many)."""

    __tablename__ = "post_tag_link"

    post_id: Mapped[int] = mapped_column(ForeignKey("post.id"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tag.id"), primary_key=True)
