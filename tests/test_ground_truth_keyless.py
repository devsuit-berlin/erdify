"""Ground truth: erdify's Pydantic / dataclass parse must match the classes' own fields (#267).

Every Pydantic and dataclass model source the suite uses (the fixtures, the
docs examples, the edge-case catalog in ``fixtures/keyless_edge_cases``, the
inline snippets of the regression tests, and every annotation the
parametrized templates in ``TEMPLATES`` are filled with) is loaded twice:
parsed by erdify from text, and executed as a module. Pydantic's
``model_fields`` and ``dataclasses.fields()`` give the fields, inherited ones
included. Both sides are reduced to field names, enums, whether each admits ``None``,
and which fields name another model of the source (erdify's relationship
edges: target, one / many, optional). Keys are not compared beyond being
absent (they exist only with ``--infer-keys``, a guess on names), nor are
table names or type display strings, which are erdify's own presentation.

Nothing is skipped silently: known differences, documented limitations,
sources the library rejects and sources that are not self-contained are each
listed below with a reason. A strict ``xfail`` turns into a failure once its
issue is fixed, an unlisted rejection or skip fails, and a listed name that no
longer exists fails.
"""

from __future__ import annotations

import dataclasses
import importlib
from pathlib import Path

import pytest

from tests.ground_truth import keyless_ref
from tests.ground_truth.schema import Schema, from_erdify
from tests.ground_truth.snippets import Snippet, keyless_snippets

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
SOURCES = ("pydantic", "dataclass")

MODULES = {
    "fixtures/pydantic": FIXTURES / "pydantic",
    "fixtures/dataclasses": FIXTURES / "dataclasses",
    **{
        f"fixtures/scan_filter/{part}": FIXTURES / "scan_filter" / part
        for part in ("app", "legacy", "site-packages/thirdparty")
    },
    "docs/examples/pydantic": ROOT / "docs" / "examples" / "pydantic",
    "docs/examples/dataclass": ROOT / "docs" / "examples" / "dataclass",
}

EDGE_CASES_DIR = FIXTURES / "keyless_edge_cases"
EDGE_CASES = sorted(EDGE_CASES_DIR.glob("*.py"))

# str.format templates a parametrized test fills with an annotation: each
# filled-in source is compared on its own, as ``<template>[<annotation>]``.
# template id -> (test module, its tests that fill the template in).
TEMPLATES = {
    "test_model_references.py::PYDANTIC": (
        "tests.test_model_references",
        ("TestKeylessReferences.test_recognized", "TestKeylessReferences.test_not_a_reference"),
    ),
    "test_column_annotations.py::PYDANTIC": (
        "tests.test_column_annotations",
        ("TestColumnNullability.test_pydantic",),
    ),
}


def _template_sources() -> list[Snippet]:
    """The templates of :data:`TEMPLATES`, filled with each of their tests' annotations."""
    found: list[Snippet] = []
    for template_id, (module_name, tests) in TEMPLATES.items():
        module = importlib.import_module(module_name)
        template = getattr(module, template_id.rpartition("::")[2])
        for test in tests:
            owner, _, method = test.partition(".")
            marks = getattr(getattr(module, owner), method).pytestmark
            for mark in marks:
                if mark.name != "parametrize":
                    continue
                argnames = mark.args[0]
                names = (
                    [n.strip() for n in argnames.split(",")]
                    if isinstance(argnames, str)
                    else list(argnames)
                )
                for values in mark.args[1]:
                    annotation = values[names.index("annotation")] if len(names) > 1 else values
                    source = template.format(annotation=annotation)
                    if "schemas." not in annotation:
                        # Only a module-qualified case needs the import of a
                        # `schemas` module, which the template doesn't define.
                        source = source.replace("import schemas\n", "")
                    found.append(Snippet(f"{template_id}[{annotation}]", 0, source))
    return found


# erdify output that differs from the library, pending a fix.
KNOWN_DIFFERENCES: dict[str, str] = {}

# Documented in docs/frameworks/limitations.md; strict xfails, so that the
# page is updated once one is supported.
LIMITATIONS = {
    "pydantic_final_default": (
        "limitations.md: Pydantic 2 makes a Final field with a default a class variable"
    ),
    # The test passes --base-classes, which the harness doesn't.
    "test_base_classes.py::test_scanned_base_class_merges_like_a_model": (
        "limitations.md: a base erdify can't resolve to BaseModel needs --base-classes"
    ),
}

# Sources Pydantic or @dataclass refuse to create that the suite still feeds
# to erdify on purpose, as robustness tests.
BROKEN_ANNOTATION = "an annotation that is no valid type; erdify must not crash"
REFS = "test_model_references.py::PYDANTIC"
COLUMNS = "test_column_annotations.py::PYDANTIC"
EXPECTED_REJECTED = {
    **{
        f"{REFS}[{annotation}]": BROKEN_ANNOTATION
        for annotation in (
            'User | "None"',  # a class | a string: TypeError at runtime
            '" User "',
            '"a\\x00b"',
            'Union[User, "a\\x00b"]',
            'Union[User, "1 +"]',
            "Union[User, 1]",
            '"User |"',
        )
    },
    **{
        f"{COLUMNS}[{annotation}]": BROKEN_ANNOTATION
        for annotation in ("Union[()]", "Annotated[()]", '"not an expression ("')
    },
    f"{COLUMNS}[NotRequired[int | None]]": (
        "NotRequired only qualifies a TypedDict key; erdify unwraps it like Final"
    ),
    "test_ground_truth_keyless.py::test_reference_reports_sources_it_cannot_load": (
        "the harness's own test of a rejected source"
    ),
}

# Sources that are not a self-contained model module, so there is nothing to
# load them into. Each is a deliberate test of erdify on partial input.
TEMPLATE = "a str.format template"
QUALIFIED = "a class of a `schemas` module the source doesn't define"
UNDEFINED = "a call to a function the source doesn't define, as a robustness test"
EXPECTED_UNLOADABLE = {
    **{
        f"{REFS}[{annotation}]": QUALIFIED
        for annotation in ("schemas.User", '"schemas.User"', "Optional[schemas.User]")
    },
    **{
        f"{REFS}[{annotation}]": UNDEFINED
        for annotation in ("get_type()", "Union[get_type(), None]", '"get()[User]"')
    },
    **{
        f"test_ground_truth_keyless.py::test_reference_reports_sources_it_cannot_load{suffix}": (
            "the harness's own test of a source that is not self-contained"
        )
        for suffix in ("[2]", "[3]")
    },
    "test_cli.py::_DC_CLI": TEMPLATE,
    "test_include.py::_DC": TEMPLATE,
    "test_inheritance.py::TestDeepDiamonds.test_stacked_diamonds_parse_quickly.lines": (
        "one line of a source the test joins from a generated list"
    ),
    "test_dialects.py::test_default_context_resolves_model_references.tree": (
        "classes for a dialect unit test, no imports"
    ),
}

SNIPPETS = [s for s in keyless_snippets() if s.id not in TEMPLATES] + _template_sources()


def _param(name: str, value: object) -> object:
    reason = KNOWN_DIFFERENCES.get(name) or LIMITATIONS.get(name)
    marks = [pytest.mark.xfail(reason=reason, raises=AssertionError, strict=True)] if reason else []
    return pytest.param(value, id=name, marks=marks)


def _assert_same(actual: Schema, expected: Schema) -> None:
    # Table names are erdify's own (the library has none): not compared.
    assert {name: dataclasses.replace(t, table="") for name, t in actual.tables.items()} == (
        expected.tables
    )
    assert actual.enums == expected.enums


def _check(name: str, source: str, tmp_path: Path, *, strict: bool = False) -> None:
    """Compare erdify with Pydantic / dataclasses for one source.

    ``strict`` sources (fixtures, docs examples, the catalog) must load; the
    lists only apply to inline snippets.
    """
    try:
        expected = keyless_ref.load(source)
    except keyless_ref.Rejected as exc:
        if name in EXPECTED_REJECTED and not strict:
            pytest.skip(f"the library rejects this source ({EXPECTED_REJECTED[name]}): {exc}")
        pytest.fail(
            f"The library rejects {name}: {exc}. Fix the source, or list it in "
            "EXPECTED_REJECTED if it is a deliberate robustness test."
        )
    except keyless_ref.Unloadable as exc:
        if name in EXPECTED_UNLOADABLE and not strict:
            pytest.skip(f"not a self-contained model module ({EXPECTED_UNLOADABLE[name]})")
        pytest.fail(f"Cannot load {name}: {exc}. Fix it or list it in EXPECTED_UNLOADABLE.")
    (tmp_path / "models.py").write_text(source, encoding="utf-8")
    _assert_same(from_erdify(tmp_path, SOURCES, relationships=True), expected)


@pytest.mark.parametrize("name", [_param(n, n) for n in sorted(MODULES)])
def test_module_matches_library(name: str, tmp_path: Path) -> None:
    source = (MODULES[name] / "models.py").read_text(encoding="utf-8")
    _check(name, source, tmp_path, strict=True)


@pytest.mark.parametrize("path", [_param(p.stem, p) for p in EDGE_CASES])
def test_edge_case_matches_library(path: Path, tmp_path: Path) -> None:
    _check(path.stem, path.read_text(encoding="utf-8"), tmp_path, strict=True)


@pytest.mark.parametrize("snippet", [_param(s.id, s) for s in SNIPPETS])
def test_snippet_matches_library(snippet: Snippet, tmp_path: Path) -> None:
    _check(snippet.id, snippet.source, tmp_path)


def test_known_lists_name_existing_sources() -> None:
    """A renamed or deleted test must not leave a stale entry behind."""
    names = {s.id for s in SNIPPETS} | {p.stem for p in EDGE_CASES} | set(MODULES)
    listed = (
        set(KNOWN_DIFFERENCES)
        | set(LIMITATIONS)
        | set(EXPECTED_REJECTED)
        | set(EXPECTED_UNLOADABLE)
    )
    assert not listed - names


def test_most_sources_are_compared() -> None:
    """Guard the discovery and the lists: most sources must really be compared."""
    listed = set(EXPECTED_REJECTED) | set(EXPECTED_UNLOADABLE)
    compared = [s for s in SNIPPETS if s.id not in listed]
    assert len(compared) >= 60
    assert len(EDGE_CASES) >= 15


def test_reference_reads_inherited_and_nested_fields() -> None:
    """The harness itself: inherited fields, forward references, collections, None."""
    schema = keyless_ref.load(
        "from typing import Optional\n\nfrom pydantic import BaseModel\n\n\n"
        "class Base(BaseModel):\n    id: int\n\n\n"
        "class Team(Base):\n    members: list['Member'] = []\n\n\n"
        "class Member(Base):\n    team: Optional[Team] = None\n    nick: str | None = None\n"
    )
    member = schema.tables["Member"]
    assert set(member.columns) == {"id", "nick"}
    assert member.columns["nick"].nullable and not member.columns["id"].nullable
    assert member.relationships["team"].kind == "one"
    assert member.relationships["team"].nullable
    assert schema.tables["Team"].relationships["members"].kind == "many"


def test_reference_takes_a_dataclass_field_from_its_declaring_class() -> None:
    """``fields()`` merges bases; ``get_type_hints()`` alone would follow Python's lookup."""
    schema = keyless_ref.load(
        "from dataclasses import dataclass\n\n\n"
        "@dataclass\nclass Root:\n    note: str\n\n\n"
        "@dataclass\nclass Left(Root):\n    pass\n\n\n"
        "@dataclass\nclass Right(Root):\n    note: str | None = None\n\n\n"
        "@dataclass\nclass Post(Left, Right):\n    pass\n"
    )
    assert schema.tables["Post"].columns["note"].nullable is False


@pytest.mark.parametrize(
    ("source", "error"),
    [
        (
            "from dataclasses import dataclass\n\n\n"
            "@dataclass\nclass A:\n    x: int = 0\n    y: int\n",
            keyless_ref.Rejected,
        ),
        ("from pydantic import BaseModel\n\n\nclass A(Unknown, BaseModel):\n    pass\n", None),
        (
            "from pydantic import BaseModel\n\n\nclass A(BaseModel):\n    b: 'Missing'\n",
            None,
        ),
    ],
    ids=["dataclass_default_order", "name", "forward_reference"],
)
def test_reference_reports_sources_it_cannot_load(
    source: str, error: type[Exception] | None
) -> None:
    with pytest.raises(keyless_ref.Unloadable) as raised:
        keyless_ref.load(source)
    assert type(raised.value) is (error or keyless_ref.Unloadable)
