"""A Pydantic field typed as another model is a relationship, in every collection."""

from collections.abc import Iterable, Mapping, Sequence
from typing import Annotated, Dict, FrozenSet, List, Optional, Set, Tuple

from pydantic import BaseModel, Field


class Author(BaseModel):
    name: str


class Tag(BaseModel):
    label: str


class Post(BaseModel):
    title: str
    author: Author
    editor: Optional[Author] = None
    reviewer: "Author | None" = None
    tags: List[Tag] = []
    tag_set: Set[Tag] = set()
    frozen_tags: FrozenSet[Tag] = frozenset()
    tag_sequence: Sequence[Tag] = ()
    tag_iterable: Iterable[Tag] = ()
    tag_tuple: Tuple[Tag, ...] = ()
    tags_by_label: Dict[str, Tag] = {}
    tag_mapping: Mapping[str, Tag] = {}
    maybe_tags: Optional[list[Tag]] = None
    tags_or_none: list[Optional[Tag]] = []
    annotated_author: Annotated[Author, Field(description="the author")]
    annotated_tags: Annotated[list[Tag], Field(max_length=5)] = []


class Comment(BaseModel):
    text: str
    post: "Post"
    parent: Optional["Comment"] = None
    replies: list["Comment"] = []
