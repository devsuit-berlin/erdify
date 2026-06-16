"""A real project app model."""

from dataclasses import dataclass


@dataclass
class Widget:
    id: int
    name: str
