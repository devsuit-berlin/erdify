"""A field one base merely inherits wins over a later base's redeclaration.

Pydantic copies inherited fields from its bases' ``model_fields``, the first
base winning, which works out like ``dataclasses.fields()``: ``Post`` gets
``Left``'s ``user`` (inherited from ``Root``), not ``Right``'s, although
``Right`` comes first in Python's MRO when looking up an annotation.
"""

from typing import ClassVar

from pydantic import BaseModel


class User(BaseModel):
    id: int


class Root(BaseModel):
    user: User
    note: str


class Left(Root):
    pass


class Right(Root):
    user: int
    note: str | None = None


class Post(Left, Right):
    id: int


class Base(BaseModel):
    tag: str


class Plain(Base):
    pass


class Hiding(Base):
    tag: ClassVar[str] = "x"


class Tagged(Plain, Hiding):
    # Hiding's class variable is the first annotation of tag in the MRO.
    pass


class Counted(BaseModel):
    count: ClassVar[int] = 0


class Counting(Counted):
    # A field again: the first annotation along the MRO decides.
    count: int | None = None


class Inheriting(Counted):
    pass


class Report(Inheriting, Counting):
    # Counting's field: Pydantic has no ClassVar pseudo-fields to inherit.
    pass
