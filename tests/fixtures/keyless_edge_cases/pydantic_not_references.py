"""Pydantic fields that mention a model but don't name exactly one: columns."""

from enum import Enum
from typing import Literal, Union

from pydantic import BaseModel


class Status(Enum):
    DRAFT = "draft"
    DONE = "done"


class Cat(BaseModel):
    name: str


class Dog(BaseModel):
    name: str


class Owner(BaseModel):
    pet: Union[Cat, Dog]
    pet_or_name: Cat | str
    pair: tuple[Cat, Dog]
    pets_by_cat: dict[Cat, int] = {}
    pets: list[Cat | Dog] = []
    status: Status = Status.DRAFT
    kind: Literal["cat", "dog"] = "cat"
