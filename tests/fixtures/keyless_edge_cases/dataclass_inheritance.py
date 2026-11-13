"""Dataclasses inherit their decorated bases' fields; a redeclaration overrides it."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class Timestamped:
    created: str
    updated: Optional[str] = None


@dataclass
class Account(Timestamped):
    id: int = 0
    owner: str = ""


@dataclass
class Admin(Account):
    # Redeclared: now admits None.
    owner: Optional[str] = None
    level: int = 1
