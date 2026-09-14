"""Models whose base class lives outside the scanned files."""

import vendor_pkg
from _vendor import Schema


class AuthorOut(Schema):
    """Direct subclass of the unscanned base."""

    id: int
    name: str


class BookOut(Schema):
    """Second direct subclass, with an inferrable foreign key."""

    id: int
    title: str
    author_id: int


class TimestampedOut(Schema):
    """Intermediate base defined here — itself a subclass of the unscanned base."""

    created_at: str


class ReviewOut(TimestampedOut):
    """Transitive: reaches the unscanned base through TimestampedOut."""

    id: int
    rating: int


class QualifiedOut(vendor_pkg.Schema):
    """Attribute form of the same base (``module.Schema``)."""

    id: int
    note: str


class NotAModel:
    """Unrelated class: must stay out of the diagram."""

    id: int
