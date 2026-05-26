"""erdify - Generate PlantUML ERD diagrams from SQLModel models."""

from .config import EntityInfo, EnumInfo, FieldInfo
from .generator import PlantUMLGenerator, generate_plantuml
from .parser import ASTDatabaseParser, parse_models_directory

__version__ = "0.1.0"

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
