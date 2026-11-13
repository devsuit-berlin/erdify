"""Every way to apply the @dataclass decorator."""

import dataclasses
from dataclasses import dataclass


@dataclass(frozen=True)
class Frozen:
    id: int


@dataclasses.dataclass
class Qualified:
    id: int


@dataclasses.dataclass(slots=True, kw_only=True)
class Slotted:
    id: int
    frozen: Frozen
