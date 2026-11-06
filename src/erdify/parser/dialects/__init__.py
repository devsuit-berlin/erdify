"""Model frameworks ("dialects"), in classification order."""

from typing import List, Tuple, Type

from .base import Dialect, ParseContext
from .django import DjangoDialect
from .keyless import DataclassDialect, PydanticDialect
from .sqlalchemy import SQLAlchemyDialect, SQLModelDialect

#: Every dialect, tried in this order when classifying a class.
DIALECTS: List[Type[Dialect]] = [
    SQLModelDialect,
    SQLAlchemyDialect,
    DjangoDialect,
    DataclassDialect,
    PydanticDialect,
]

#: Model frameworks erdify can recognize, in classification order.
MODEL_SOURCES: Tuple[str, ...] = tuple(dialect.kind for dialect in DIALECTS)

__all__ = ["DIALECTS", "MODEL_SOURCES", "Dialect", "ParseContext"]
