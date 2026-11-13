"""``Final`` with a default: a class variable in Pydantic 2, a field in Pydantic 3.

Pydantic 2.11 deprecated treating it as a class variable; erdify draws it as a
field, like a dataclass and like Pydantic 3.
"""

from typing import Final

from pydantic import BaseModel


class Settings(BaseModel):
    name: str
    version: Final[int] = 1
    # Without a default, Final is a field in every Pydantic.
    region: Final[str]
