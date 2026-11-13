"""A field one base merely inherits wins over a later base's redeclaration.

``dataclasses.fields()`` merges each base's fields in reversed MRO order:
``Post`` gets ``Left``'s ``note`` (inherited from ``Root``), not ``Right``'s.
"""

from dataclasses import dataclass


@dataclass
class Root:
    note: str


@dataclass
class Left(Root):
    pass


@dataclass
class Right(Root):
    note: str | None = None


@dataclass
class Post(Left, Right):
    id: int = 0
