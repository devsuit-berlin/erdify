"""A dataclass field typed as another dataclass is a relationship, in every collection."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class Author:
    name: str


@dataclass
class Tag:
    label: str


@dataclass
class Post:
    title: str
    author: Author
    editor: Optional[Author] = None
    reviewer: "Author | None" = None
    tags: List[Tag] = field(default_factory=list)
    tag_set: set[Tag] = field(default_factory=set)
    tag_sequence: Sequence[Tag] = ()
    tag_tuple: Tuple[Tag, ...] = ()
    tags_by_label: Dict[str, Tag] = field(default_factory=dict)
    maybe_tags: Optional[list[Tag]] = None


@dataclass
class Comment:
    text: str
    post: "Post"
    parent: Optional["Comment"] = None
    replies: list["Comment"] = field(default_factory=list)
