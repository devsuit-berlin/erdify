"""erdify - Generate PlantUML ERD diagrams from your models."""

from importlib.metadata import PackageNotFoundError, version

from .config import EntityInfo, EnumInfo, FieldInfo
from .edges import Edge, EdgeEnd, EdgeKind, diagram_edges
from .enums import enum_users
from .generator import (
    JSON_SCHEMA_VERSION,
    MermaidGenerator,
    PlantUMLGenerator,
    generate_html,
    generate_json,
    generate_mermaid,
    generate_plantuml,
)
from .parser import ASTDatabaseParser, ModelParseError, parse_models_directory
from .project import Project, Settings, load_project, resolve_settings
from .pyproject import ConfigError
from .sql_parser import SqlDependencyError, SqlSchemaParser

try:
    __version__ = version("erdify")
except PackageNotFoundError:  # package is not installed (e.g. running from a raw checkout)
    __version__ = "0.0.0+unknown"

__all__ = [
    # Data classes
    "FieldInfo",
    "EnumInfo",
    "EntityInfo",
    # Edges
    "Edge",
    "EdgeEnd",
    "EdgeKind",
    "diagram_edges",
    # Enums
    "enum_users",
    # Parser
    "ASTDatabaseParser",
    "parse_models_directory",
    "ModelParseError",
    "SqlSchemaParser",
    "SqlDependencyError",
    # Project (resolve settings and parse like the CLI)
    "load_project",
    "resolve_settings",
    "Project",
    "Settings",
    "ConfigError",
    # Generator
    "PlantUMLGenerator",
    "generate_plantuml",
    "MermaidGenerator",
    "generate_mermaid",
    "generate_json",
    "JSON_SCHEMA_VERSION",
    "generate_html",
    # Version
    "__version__",
]
