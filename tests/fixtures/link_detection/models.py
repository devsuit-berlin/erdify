"""Structural link-table detection fixture (#35, #118).

Link tables must be detected by structure - a composite primary key made up
entirely of foreign keys, with no payload columns - not by the '*Link*' name
heuristic. This fixture covers three directions:

- ``PostTag`` is a binary association table that is NOT named ``*Link*`` but
  must still be recognized as a join table and drawn as an M:N path.
- ``LinkPreview`` contains "Link" in its name but has a normal (non-join)
  structure and must NOT be misclassified as a link table.
- ``ProjectMembership`` is a ternary association table (composite PK of three
  FKs) that must be recognized as a link table and drawn as a star of edges
  from each parent to the link entity (#118).
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
    tags: Mapped[List["Tag"]] = relationship(secondary="post_tag", back_populates="posts")


class Tag(Base):
    """Tag entity."""

    __tablename__ = "tag"

    id: Mapped[int] = mapped_column(primary_key=True)
    posts: Mapped[List["Post"]] = relationship(secondary="post_tag", back_populates="tags")


class PostTag(Base):
    """Association table for the post <-> tag M:N - intentionally not named *Link*."""

    __tablename__ = "post_tag"

    post_id: Mapped[int] = mapped_column(ForeignKey("post.id"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tag.id"), primary_key=True)


class LinkPreview(Base):
    """A normal entity that merely has "Link" in its name - NOT a join table."""

    __tablename__ = "link_preview"

    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column()
    title: Mapped[str] = mapped_column()


class Project(Base):
    """Project entity - one leg of the ternary association."""

    __tablename__ = "project"

    id: Mapped[int] = mapped_column(primary_key=True)


class User(Base):
    """User entity - one leg of the ternary association."""

    __tablename__ = "user"

    id: Mapped[int] = mapped_column(primary_key=True)


class Role(Base):
    """Role entity - one leg of the ternary association."""

    __tablename__ = "role"

    id: Mapped[int] = mapped_column(primary_key=True)


class ProjectMembership(Base):
    """Ternary association table: a composite PK of three FKs, no payload (#118)."""

    __tablename__ = "project_membership"

    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("role.id"), primary_key=True)
