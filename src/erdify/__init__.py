"""erdify - Generate PlantUML ERD diagrams from your models."""

from importlib.metadata import PackageNotFoundError, version

from .config import EntityInfo, EnumInfo, FieldInfo
from .generator import PlantUMLGenerator, generate_plantuml
from .parser import ASTDatabaseParser, parse_models_directory

try:
    __version__ = version("erdify")
except PackageNotFoundError:  # package is not installed (e.g. running from a raw checkout)
    __version__ = "0.0.0+unknown"

__all__ = [
    # Data classes
    "FieldInfo",
    "EnumInfo",
    "EntityInfo",
    # Parser
    "ASTDatabaseParser",
    "parse_models_directory",
    # Generator
    "PlantUMLGenerator",
    "generate_plantuml",
    # Version
    "__version__",
]
