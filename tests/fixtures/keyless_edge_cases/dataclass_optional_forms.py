"""Every spelling of a dataclass field that admits None, and look-alikes that don't."""

from dataclasses import dataclass
from typing import Annotated, Literal, Optional, Union


@dataclass
class Profile:
    required: int
    optional: Optional[str] = None
    pipe: str | None = None
    none_first: None | int = None
    union: Union[int, None] = None
    multi_union: Union[int, str, None] = None
    literal: Literal["a", "b", None] = None
    annotated: Annotated[int | None, "metadata"] = None
    quoted: "str | None" = None
    # A default of None doesn't make the type admit None.
    defaulted_none: int = None  # type: ignore[assignment]
    defaulted: int = 0
