"""AST-based parser for SQLModel, SQLAlchemy, Django, Pydantic and dataclass models.

Public API: :class:`ASTDatabaseParser`, :func:`parse_models_directory`,
:func:`scan_report` / :class:`ScanReport`, :class:`ModelParseError`,
:data:`MODEL_SOURCES` and :data:`DEFAULT_EXCLUDE_DIRS`. The submodules are
internal and may change in any release.
"""

from .core import (
    ASTDatabaseParser,
    ModelParseError,
    ScanReport,
    parse_models_directory,
    scan_report,
)
from .discovery import DEFAULT_EXCLUDE_DIRS, _match_include, _translate_glob
from .common import MODEL_SOURCES

__all__ = [
    "ASTDatabaseParser",
    "DEFAULT_EXCLUDE_DIRS",
    "MODEL_SOURCES",
    "ModelParseError",
    "ScanReport",
    "parse_models_directory",
    "scan_report",
    "_match_include",
    "_translate_glob",
]
