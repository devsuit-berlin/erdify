"""Pydantic models inherit their bases' fields; a redeclaration overrides it."""

from typing import Optional

from pydantic import BaseModel


class Timestamped(BaseModel):
    created: str
    updated: Optional[str] = None


class Account(Timestamped):
    id: int
    owner: str


class Admin(Account):
    # Redeclared: now admits None.
    owner: Optional[str] = None
    level: int = 1
