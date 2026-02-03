"""Sample SQLModel models for testing - inheritance patterns."""

from datetime import datetime

from sqlmodel import Field, SQLModel


class TimestampMixin(SQLModel):
    """Mixin for timestamp fields."""

    created_at: datetime
    updated_at: datetime | None = None


class BaseEntity(TimestampMixin):
    """Base entity with ID and timestamps."""

    id: int = Field(primary_key=True)


class Article(BaseEntity, table=True):
    """Article entity inheriting from BaseEntity."""

    __tablename__: str = "article"

    title: str
    content: str
    published: bool = Field(default=False)


class Comment(BaseEntity, table=True):
    """Comment entity inheriting from BaseEntity."""

    __tablename__: str = "comment"

    article_id: int = Field(foreign_key="article.id")
    author_name: str
    body: str
