"""Ground truth: erdify's Django parse must match what Django builds (#264).

Every Django model source the suite uses (the fixture app, the docs example,
the edge-case catalog in ``fixtures/django_edge_cases`` and the inline snippets
of the regression tests) is loaded twice: parsed by
erdify from text, and executed by Django into an isolated app registry. Both
are reduced to the same normalised schema (tables, columns, primary / unique /
foreign keys, nullability, many-to-many edges, choices enums) and must agree.

Nothing is skipped silently: known differences, sources Django rejects and
sources that are not self-contained are each listed below with a reason. A
strict ``xfail`` turns into a failure once its issue is fixed, an unlisted
rejection or skip fails, and a listed name that no longer exists fails.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.ground_truth import django_ref
from tests.ground_truth.schema import Schema, from_erdify
from tests.ground_truth.snippets import Snippet, django_snippets

ROOT = Path(__file__).resolve().parent.parent

MODULES = {
    "fixtures/django": ROOT / "tests" / "fixtures" / "django",
    "docs/examples/django": ROOT / "docs" / "examples" / "django",
}

EDGE_CASES_DIR = ROOT / "tests" / "fixtures" / "django_edge_cases"
EDGE_CASES = sorted(EDGE_CASES_DIR.glob("*.py"))

# erdify output that differs from Django's schema, pending a fix.
KNOWN_DIFFERENCES = {
    "test_inheritance.py::DJANGO_DIAMOND": (
        "#272: diamond abstract inheritance follows Python's MRO, Django keeps the first copy"
    ),
    "test_dialects.py::test_django_table_args_uniqueness_kept": (
        "#274: SQLAlchemy __table_args__ is applied to a Django model"
    ),
    "test_inheritance.py::TestDjangoSelfOwnerEdgeCases.test_plain_mixin_self_binds_to_the_model"
    ".src": "#280: a field on a plain (non-Model) mixin is not a column in Django",
    # Edge-case catalog (tests/fixtures/django_edge_cases).
    "abstract_meta_inheritance": "#279: Meta.db_table inherited from an abstract base",
    "composite_primary_key": "#276: CompositePrimaryKey is not supported",
    "meta_constraints": "#274: a single-field Meta.constraints UniqueConstraint is not read",
}

# Sources where Django itself builds an inconsistent model, so there is no
# schema to hold erdify to.
DEGENERATE = {
    "test_django_mti.py::TestOverriddenLinks.SRC": (
        "Removing or overriding an abstract parent_link leaves Django with the abstract "
        "base's field (or a CharField) as the parent link and primary key"
    ),
}

# Sources whose schema depends on project settings the reference can't mirror:
# it runs with Django's default AUTH_USER_MODEL (auth.User), while erdify
# resolves settings.AUTH_USER_MODEL to the source's own user model (#278).
# Covered by unit tests in test_django.py instead.
SETTINGS_DEPENDENT = {
    "test_django.py::TestDjangoContribAuth.CUSTOM_USER": "swapped AUTH_USER_MODEL",
}

# Sources Django refuses to build (FieldError) that the suite still feeds to
# erdify on purpose, as robustness tests.
EXPECTED_REJECTED = {
    "test_django_mti.py::TestToFieldOnInheritedColumns.SRC": "#273",
    "test_django_mti.py::TestInheritedKeys.test_to_field_id_references_the_parent.entities": (
        "#273"
    ),
    "test_django_mti.py::TestInheritedKeys"
    ".test_chained_inherited_to_field_keeps_its_type.entities": "#273",
    "test_django_mti.py::TestInheritedKeys"
    ".test_removed_inherited_primary_key_restores_implicit_id.entities": "#273",
    "test_django_mti.py::TestProxyModels.test_proxy_without_concrete_model_links_nothing"
    ".entities": "a proxy needs a concrete base; erdify must not crash on it",
}

# Sources that are not a self-contained Django module, so there is nothing to
# load them into. Each is a deliberate test of erdify on partial input.
EXPECTED_UNLOADABLE = {
    "test_django.py::TestDjangoContribAuth"
    ".test_another_modules_contrib_import_does_not_leak.entities[2]": (
        "imports Group from a module outside the source"
    ),
    "test_django.py::TestDjangoDefaultTableNames.test_foreign_key_uses_the_target_app": (
        "relation to a model in another app's file"
    ),
    "test_base_classes.py::TestModelDerivedSchemas.DJANGO_MODEL": "imports django-ninja",
    "test_cardinality.py::TestDjangoInheritedOverride.BASE": "str.format template",
    "test_cardinality.py::TestDeclaredRelationshipNullability.DJANGO": "str.format template",
    "test_cardinality.py::TestDjangoForeignKeyTarget.SRC": "relation to a model outside the file",
    "test_cardinality.py::TestDjangoForeignKeyTarget.test_pk_with_unresolvable_target.src": (
        "relation to a model outside the file"
    ),
}

SNIPPETS = django_snippets()


def _param(name: str, value: object) -> object:
    marks = []
    if name in KNOWN_DIFFERENCES:
        marks.append(
            pytest.mark.xfail(reason=KNOWN_DIFFERENCES[name], raises=AssertionError, strict=True)
        )
    return pytest.param(value, id=name, marks=marks)


def _assert_same(actual: Schema, expected: Schema) -> None:
    assert actual.tables == expected.tables
    assert actual.enums == expected.enums


def _erdify(source: str, tmp_path: Path) -> Schema:
    """Parse ``source`` with erdify as the ``models.py`` of an app labelled like the reference's."""
    app = tmp_path / django_ref.APP_LABEL
    app.mkdir()
    (app / "models.py").write_text(source, encoding="utf-8")
    return from_erdify(app, "django")


@pytest.mark.parametrize("name", sorted(MODULES))
def test_module_matches_django(name: str, tmp_path: Path) -> None:
    source = (MODULES[name] / "models.py").read_text(encoding="utf-8")
    expected = django_ref.load(source)
    assert expected.tables, "the reference loader found no models"
    _assert_same(_erdify(source, tmp_path), expected)


def _check(name: str, source: str, tmp_path: Path) -> None:
    if name in DEGENERATE:
        pytest.skip(DEGENERATE[name])
    if name in SETTINGS_DEPENDENT:
        pytest.skip(f"depends on project settings: {SETTINGS_DEPENDENT[name]}")
    try:
        expected = django_ref.load(source)
    except django_ref.Rejected as exc:
        if name in EXPECTED_REJECTED:
            pytest.skip(f"Django rejects this source ({EXPECTED_REJECTED[name]}): {exc}")
        pytest.fail(
            f"Django rejects {name}: {exc}. Fix the source, or list it in "
            "EXPECTED_REJECTED if it is a deliberate robustness test."
        )
    except django_ref.Unloadable as exc:
        if name in EXPECTED_UNLOADABLE:
            pytest.skip(f"not a self-contained Django module ({EXPECTED_UNLOADABLE[name]})")
        pytest.fail(f"Django cannot load {name}: {exc}. Fix it or list it in EXPECTED_UNLOADABLE.")
    _assert_same(_erdify(source, tmp_path), expected)


@pytest.mark.parametrize("snippet", [_param(s.id, s) for s in SNIPPETS])
def test_snippet_matches_django(snippet: Snippet, tmp_path: Path) -> None:
    _check(snippet.id, snippet.source, tmp_path)


@pytest.mark.parametrize("path", [_param(p.stem, p) for p in EDGE_CASES])
def test_edge_case_matches_django(path: Path, tmp_path: Path) -> None:
    _check(path.stem, path.read_text(encoding="utf-8"), tmp_path)


def test_known_lists_name_existing_snippets() -> None:
    """A renamed or deleted test must not leave a stale entry behind."""
    names = {s.id for s in SNIPPETS} | {p.stem for p in EDGE_CASES}
    listed = (
        set(KNOWN_DIFFERENCES)
        | set(DEGENERATE)
        | set(SETTINGS_DEPENDENT)
        | set(EXPECTED_REJECTED)
        | set(EXPECTED_UNLOADABLE)
    )
    assert not listed - names


def test_most_sources_are_compared() -> None:
    """Guard the discovery and the lists: most sources must really be compared."""
    listed = (
        set(DEGENERATE)
        | set(SETTINGS_DEPENDENT)
        | set(EXPECTED_REJECTED)
        | set(EXPECTED_UNLOADABLE)
    )
    compared = [s for s in SNIPPETS if s.id not in listed]
    assert len(compared) >= 40
    assert len(EDGE_CASES) >= 15
