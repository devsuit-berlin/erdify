"""Command-line interface for erdify."""

import argparse
import sys
from pathlib import Path

from .generator import generate_plantuml
from .parser import parse_models_directory


def main() -> int:
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        prog="erdify",
        description="Generate PlantUML ERD diagrams from SQLModel models",
        epilog="Example: erdify ./src/database -o database_erd.puml",
    )
    parser.add_argument(
        "input",
        type=Path,
        help="Directory containing model files (searches for models.py recursively)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output .puml file (default: stdout)",
    )
    parser.add_argument(
        "--title",
        default="Database ERD",
        help="Diagram title (default: 'Database ERD')",
    )
    parser.add_argument(
        "--exclude",
        nargs="*",
        default=[],
        help="Patterns to exclude (not yet implemented)",
    )
    parser.add_argument(
        "--no-enums",
        action="store_true",
        help="Skip enum definitions in output",
    )
    parser.add_argument(
        "--no-relationships",
        action="store_true",
        help="Skip relationship lines in output",
    )
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version="%(prog)s 0.1.0",
    )

    args = parser.parse_args()

    # Validate input path
    if not args.input.exists():
        print(f"Error: Input path does not exist: {args.input}", file=sys.stderr)
        return 1

    if not args.input.is_dir():
        print(f"Error: Input path is not a directory: {args.input}", file=sys.stderr)
        return 1

    # Parse models
    try:
        entities, enums = parse_models_directory(args.input, args.exclude)
    except Exception as e:
        print(f"Error parsing models: {e}", file=sys.stderr)
        return 1

    if not entities:
        print(
            f"Warning: No SQLModel tables found in {args.input}",
            file=sys.stderr,
        )

    # Generate PlantUML
    output = generate_plantuml(
        entities=entities,
        enums=enums,
        title=args.title,
        include_enums=not args.no_enums,
        include_relationships=not args.no_relationships,
    )

    # Write output
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output)
        print(f"Generated ERD diagram: {args.output}", file=sys.stderr)
        print(f"  Found {len(entities)} entities and {len(enums)} enums", file=sys.stderr)
    else:
        print(output)

    return 0
