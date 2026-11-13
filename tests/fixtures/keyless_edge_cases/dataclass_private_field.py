"""A dataclass field whose name starts with an underscore is still a field."""

from dataclasses import dataclass


@dataclass
class Account:
    id: int
    _balance: int = 0
