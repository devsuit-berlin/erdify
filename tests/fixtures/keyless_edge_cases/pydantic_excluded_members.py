"""Class members of a Pydantic model that are not fields."""

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, PrivateAttr, computed_field


class Order(BaseModel):
    model_config = ConfigDict(frozen=True)

    registry: ClassVar[dict[str, int]] = {}
    _cache: dict[str, int] = PrivateAttr(default_factory=dict)
    _secret: int = 0

    id: int
    amount: float

    @computed_field
    @property
    def doubled(self) -> float:
        return self.amount * 2

    @property
    def label(self) -> str:
        return f"#{self.id}"

    def total(self) -> float:
        return self.amount


class Shadowed(Order):
    # A class variable redeclaring an inherited field removes it.
    amount: ClassVar[float] = 1.0


class Grand(Shadowed):
    extra: int = 0


class Mixin:
    id: ClassVar[int] = 0


class MixedFirst(Mixin, Order):
    # The mixin's class variable comes first in the MRO: id is no field.
    pass
