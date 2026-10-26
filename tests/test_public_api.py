"""Pin the public Python API (#195): changing it is a semver decision."""

import erdify


def test_public_api_is_pinned():
    """Removing a name is breaking; adding one makes it a 1.0 contract.
    Update docs/usage/cli.md ("Python API") alongside this list."""
    assert sorted(erdify.__all__) == sorted(
        [
            "FieldInfo",
            "EnumInfo",
            "EntityInfo",
            "ASTDatabaseParser",
            "parse_models_directory",
            "SqlSchemaParser",
            "SqlDependencyError",
            "PlantUMLGenerator",
            "generate_plantuml",
            "MermaidGenerator",
            "generate_mermaid",
            "generate_json",
            "JSON_SCHEMA_VERSION",
            "generate_html",
            "__version__",
        ]
    )


def test_every_public_name_is_importable():
    for name in erdify.__all__:
        assert hasattr(erdify, name), name
