"""AST-based parser for SQLModel, SQLAlchemy, Django, Pydantic and dataclass models.

Re-exports what :mod:`erdify` and the CLI use. The stable public surface is
``erdify.__all__``; this package and its submodules are internal and may
change in any release.
"""

from .core import (
    ASTDatabaseParser,
    ModelParseError,
    ScanReport,
    parse_models_directory,
    scan_report,
)
from .dialects import MODEL_SOURCES
from .discovery import DEFAULT_EXCLUDE_DIRS, _match_include, _translate_glob  # noqa: F401

__all__ = [
    "ASTDatabaseParser",
    "DEFAULT_EXCLUDE_DIRS",
    "MODEL_SOURCES",
    "ModelParseError",
    "ScanReport",
    "parse_models_directory",
    "scan_report",
]
