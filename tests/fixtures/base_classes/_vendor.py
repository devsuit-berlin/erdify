"""Stand-in for a base class defined in an installed package.

This file is deliberately NOT named models.py, so the default ``--include``
never scans it. That reproduces the real condition: ``ninja.Schema`` subclasses
``pydantic.BaseModel``, but the inheritance lives inside the installed package
and erdify resolves ancestors only across the files it scans.
"""

from pydantic import BaseModel


class Schema(BaseModel):
    """Equivalent of ``ninja.Schema``."""
