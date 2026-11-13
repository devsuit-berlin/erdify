"""A field one base merely inherits wins over a later base's redeclaration.

Pydantic merges each base's ``model_fields`` in reversed MRO order, like
``dataclasses.fields()``: ``Post`` gets ``Left``'s ``user`` (inherited from
``Root``), not ``Right``'s, although ``Right`` comes first in Python's MRO
when looking up an annotation.
"""

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
