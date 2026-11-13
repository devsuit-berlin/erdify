"""Pydantic's own @dataclass: a dataclass, read like the standard library's."""

from typing import Optional

from pydantic.dataclasses import dataclass


@dataclass
class Point:
    x: int
    y: int
    label: Optional[str] = None


@dataclass
class Segment:
    start: Point
    end: Point
