"""Class members of a dataclass that are not fields, and fields that are easy to miss."""

from dataclasses import KW_ONLY, InitVar, dataclass, field
from typing import ClassVar, Final


@dataclass
class Order:
    registry: ClassVar[dict[str, int]] = {}
    id: int
    seed: InitVar[int]
    _: KW_ONLY
    amount: float = 0.0
    # init=False and repr=False still make a field.
    total: float = field(init=False, default=0.0)
    secret: str = field(repr=False, default="")
    version: Final[int] = 1

    def __post_init__(self, seed: int) -> None:
        self.total = self.amount * seed

    @property
    def label(self) -> str:
        return f"#{self.id}"


@dataclass
class Shadowed(Order):
    # A class variable redeclaring an inherited field removes it.
    amount: ClassVar[float] = 1.0
