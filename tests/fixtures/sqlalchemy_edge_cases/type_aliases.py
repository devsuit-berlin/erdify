"""Column settings from Annotated metadata and module-level type aliases."""

from typing import Annotated

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

intpk = Annotated[int, mapped_column(primary_key=True)]
str50 = Annotated[str, mapped_column(String(50))]
user_fk = Annotated[int, mapped_column(ForeignKey("user_account.id"))]
unique_code = Annotated[str, mapped_column(unique=True)]
optional_note = Annotated[str | None, mapped_column(String(10))]


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "user_account"

    id: Mapped[intpk]
    name: Mapped[str50]
    code: Mapped[unique_code]


class Post(Base):
    __tablename__ = "post"

    id: Mapped[intpk]
    author_id: Mapped[user_fk]
    note: Mapped[optional_note]
    inline: Mapped[Annotated[str, mapped_column(unique=True)]]
    overridden: Mapped[unique_code] = mapped_column(unique=False)
