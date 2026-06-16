"""Command-line interface for erdify."""

import argparse
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .generator import generate_plantuml
from .parser import MODEL_SOURCES, parse_models_directory
from .pyproject import load_config


def main() -> int:
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        prog="erdify",
        description=(
            "Generate PlantUML ERD diagrams from SQLModel, SQLAlchemy, Django, "
            "Pydantic and dataclass models"
        ),
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
        default=None,
        help="Diagram title (default: 'Database ERD')",
    )
    parser.add_argument(
        "--exclude",
        nargs="*",
        default=None,
        metavar="PATTERN",
        help=(
            "Glob patterns (case-sensitive) to exclude entities by class name "
            "or table name, e.g. --exclude '*Link' audit_log"
        ),
    )
    parser.add_argument(
        "--exclude-paths",
        nargs="*",
        default=None,
        metavar="PATTERN",
        help=(
            "Glob patterns (case-sensitive) for models.py files to skip before "
            "parsing, matched against the path relative to input or any path "
            "segment, e.g. --exclude-paths migrations legacy 'apps/experimental/*'"
        ),
    )
    parser.add_argument(
        "--no-default-excludes",
        action="store_true",
        help=(
            "Do not auto-skip models.py under venv/site-packages/cache dirs "
            "(.venv, site-packages, __pycache__, ...); scan them too"
        ),
    )
    parser.add_argument(
        "--sources",
        nargs="*",
        choices=MODEL_SOURCES,
        metavar="KIND",
        help=(
            "Restrict which model kinds become entities. Choices: "
            f"{', '.join(MODEL_SOURCES)}. Default: all. "
            "e.g. --sources sqlmodel sqlalchemy for DB tables only"
        ),
    )
    parser.add_argument(
        "--infer-keys",
        action="store_true",
        help=(
            "For keyless models (Pydantic/dataclass), infer a primary key from a "
            "field named 'id' and a foreign key from '<x>_id' (target table '<x>')"
        ),
    )
    parser.add_argument(
        "--django-raw-types",
        action="store_true",
        help=(
            "For Django models, show original field names (CharField, TextField) "
            "instead of mapped Python types (str, int, datetime)"
        ),
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
        "--check",
        action="store_true",
        help=(
            "Don't write; exit non-zero if the --output file is missing or differs "
            "from the freshly generated diagram (for CI / pre-commit drift checks)"
        ),
    )
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    args = parser.parse_args()

    # Validate input path
    if not args.input.exists():
        print(f"Error: Input path does not exist: {args.input}", file=sys.stderr)
        return 1

    if not args.input.is_dir():
        print(f"Error: Input path is not a directory: {args.input}", file=sys.stderr)
        return 1

    # Resolve settings: explicit CLI flag > [tool.erdify] in pyproject.toml > default.
    config, base_dir = load_config(args.input)

    def pick(cli_value: Any, key: str, default: Any) -> Any:
        return cli_value if cli_value is not None else config.get(key, default)

    title = pick(args.title, "title", "Database ERD")
    sources = pick(args.sources, "sources", None)
    exclude = pick(args.exclude, "exclude", [])
    exclude_paths = pick(args.exclude_paths, "exclude_paths", [])
    # Boolean flags merge by OR (a flag enabled in config or on the CLI is enabled).
    infer_keys = args.infer_keys or bool(config.get("infer_keys", False))
    django_raw_types = args.django_raw_types or bool(config.get("django_raw_types", False))
    no_enums = args.no_enums or bool(config.get("no_enums", False))
    no_relationships = args.no_relationships or bool(config.get("no_relationships", False))
    no_default_excludes = args.no_default_excludes or bool(config.get("no_default_excludes", False))

    # Output: CLI path (relative to cwd) > config path (relative to the project) > stdout.
    output_path: Path | None = args.output
    if output_path is None and "output" in config:
        output_path = Path(config["output"])
        if not output_path.is_absolute() and base_dir is not None:
            output_path = base_dir / output_path

    if args.check and output_path is None:
        print(
            "Error: --check requires --output (or 'output' in [tool.erdify])",
            file=sys.stderr,
        )
        return 2

    # Parse models
    try:
        entities, enums = parse_models_directory(
            args.input,
            exclude,
            infer_keys=infer_keys,
            sources=sources,
            django_raw_types=django_raw_types,
            exclude_paths=exclude_paths,
            use_default_excludes=not no_default_excludes,
        )
    except Exception as e:
        print(f"Error parsing models: {e}", file=sys.stderr)
        return 1

    if not entities:
        print(
            f"Warning: No tables found in {args.input}",
            file=sys.stderr,
        )

    # Generate PlantUML
    output = generate_plantuml(
        entities=entities,
        enums=enums,
        title=title,
        include_enums=not no_enums,
        include_relationships=not no_relationships,
    )

    # Check mode: compare against the existing file, never write.
    if args.check:
        assert output_path is not None  # guarded above
        existing = output_path.read_text() if output_path.exists() else None
        if existing == output:
            print(f"ERD is up to date: {output_path}", file=sys.stderr)
            return 0
        reason = "differs from" if existing is not None else "is missing at"
        print(
            f"Error: generated ERD {reason} {output_path}. Re-run erdify to update it.",
            file=sys.stderr,
        )
        return 1

    # Write output
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output)
        print(f"Generated ERD diagram: {output_path}", file=sys.stderr)
        print(f"  Found {len(entities)} entities and {len(enums)} enums", file=sys.stderr)
    else:
        print(output)

    return 0
