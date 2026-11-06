"""Model frameworks ("dialects"), in classification order."""

from typing import List, Type

from .base import Dialect, ParseContext
from .django import DjangoDialect
from .keyless import DataclassDialect, PydanticDialect
from .sqlalchemy import SQLAlchemyDialect, SQLModelDialect, core_association_tables

#: Tried in this order; matches ``MODEL_SOURCES``.
DIALECTS: List[Type[Dialect]] = [
    SQLModelDialect,
    SQLAlchemyDialect,
    DjangoDialect,
    DataclassDialect,
    PydanticDialect,
]

__all__ = ["DIALECTS", "Dialect", "ParseContext", "core_association_tables"]
