"""Every spelling of a Pydantic field that admits None, and look-alikes that don't."""

from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field


class Profile(BaseModel):
    optional: Optional[str] = None
    pipe: str | None = None
    none_first: None | int = None
    union: Union[int, None] = None
    multi_union: Union[int, str, None] = None
    literal: Literal["a", "b", None] = None
    annotated: Annotated[int | None, Field(ge=0)] = None
    quoted: "str | None" = None
    # A default of None doesn't make the type admit None.
    required: int
    defaulted: int = 0
    union_without_none: int | str = 0
    literal_without_none: Literal["a", "b"] = "a"
