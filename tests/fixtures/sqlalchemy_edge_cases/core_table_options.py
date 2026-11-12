"""Core Table(...) column options and table-level constraints, and __table__ by variable."""

import sqlalchemy as sa
from sqlalchemy import (
    Column,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, relationship


class Base(DeclarativeBase):
    pass


shelf_table = Table(
    "shelf",
    Base.metadata,
    Column("id", Integer, primary_key=True),
    Column("code", String(10), nullable=False),
)


class Shelf(Base):
    # A class mapped to a module-level table: drawn once, under the class.
    __table__ = shelf_table

    books: Mapped[list["Book"]] = relationship(back_populates="shelf")


class Book(Base):
    __table__ = Table(
        "book",
        Base.metadata,
        Column("id", Integer, primary_key=True),
        Column("shelf_id", ForeignKey("shelf.id")),
    )

    shelf: Mapped["Shelf | None"] = relationship(back_populates="books")


tag = sa.Table(
    "tag",
    Base.metadata,
    sa.Column(sa.Integer, name="id", primary_key=True),
    sa.Column("slug", type_=sa.String(30), nullable=False),
    sa.Column("title", sa.String(50), nullable=True),
    sa.UniqueConstraint("slug"),
)

edition = Table(
    "edition",
    Base.metadata,
    Column("book_id", Integer, nullable=False),
    Column("number", Integer, nullable=False),
    Column("isbn", String(13)),
    Column("book_ref", ForeignKey("book.id", ondelete="CASCADE"), key="book"),
    PrimaryKeyConstraint("book_id", "number"),
    ForeignKeyConstraint(["book_id"], ["book.id"]),
    Index("ix_edition_isbn", "isbn", unique=True),
)

review = Table(
    "review",
    Base.metadata,
    Column("id", Integer, primary_key=True),
    # A constraint names a column through its key.
    Column("edition_book", Integer, key="eb"),
    Column("edition_number", Integer),
    UniqueConstraint("eb"),
    # Composite: makes neither column unique on its own.
    UniqueConstraint("eb", "edition_number"),
)

# A foreign key names the referenced column through its key too.
region = Table(
    "region",
    Base.metadata,
    Column("region_id", Integer, key="id", primary_key=True),
)

office = Table(
    "office",
    Base.metadata,
    Column("id", Integer, primary_key=True),
    Column("region", ForeignKey("region.id"), nullable=False),
)

# Keyword-only columns, and an annotated table variable.
keyword_only: Table = Table(
    "keyword_only",
    Base.metadata,
    Column(name="id", type_=Integer, primary_key=True),
    Column(name="label", type_=String(20), nullable=False),
)
