"""Ground truth: erdify's Django parse must match what Django builds (#264).

Every Django model source the suite uses (the fixture app, the docs example,
the edge-case catalog in ``fixtures/django_edge_cases`` and the inline snippets
of the regression tests) is loaded twice: parsed by
erdify from text, and executed by Django into an isolated app registry. Both
are reduced to the same normalised schema (tables, columns, primary / unique /
foreign keys, nullability, many-to-many edges, choices enums) and must agree.

Every source is loaded the way a Django project runs it, and Django's model
checks (the ``models`` checks of ``manage.py check``) must pass (#287): test
data that no project could run is caught.

Nothing is skipped silently: known differences, sources Django rejects,
sources that are not self-contained and deliberate check errors are each
listed below with a reason. A
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
KNOWN_DIFFERENCES: dict[str, str] = {}

# Documented in docs/frameworks/limitations.md; strict xfails, so that the
# page is updated once one is supported.
LIMITATIONS = {
    "test_django.py::TestDjangoCompositePrimaryKey.test_non_literal_key_adds_no_id.src": (
        "limitations.md: non-literal CompositePrimaryKey arguments mark no column as the key"
    ),
}

# Sources where Django itself builds an inconsistent model, so there is no
# schema to hold erdify to.
DEGENERATE = {
    "test_django_mti.py::TestOverriddenLinks.SRC": (
        "Removing or overriding an abstract parent_link leaves Django with the abstract "
        "base's field (or a CharField) as the parent link and primary key"
    ),
}

# Inline snippets that fail Django's system checks on purpose: error ids and
# why. Every other source must pass the checks (#287), and the fixture app,
# the docs example and the edge-case catalog always must.
EXPECTED_CHECK_ERRORS = {
    "test_ground_truth_django.py::OUTSIDE_LABELS": (
        ("models.E028",),
        "the harness's own test of cross-model checks for other app labels",
    ),
    "test_ground_truth_django.py::MIXED_LABELS": (
        ("models.E028",),
        "the harness's own test of cross-model checks across app labels",
    ),
    "test_ground_truth_django.py::INVALID_USER": (
        ("auth.E003",),
        "the harness's own test that auth's user-model checks run",
    ),
    "test_ground_truth_django.py::test_reference_runs_cross_model_checks.shared": (
        ("models.E028",),
        "the harness's own test that cross-model checks run",
    ),
    "test_ground_truth_django.py::test_reference_reports_system_check_errors.bad": (
        ("fields.E120",),
        "the harness's own test that check errors are reported",
    ),
    "test_cardinality.py::TestPrimaryKeyNotNullableAcrossSources.test_django_null_pk.src": (
        ("fields.E007",),
        "a primary key with null=True: erdify must still draw it NOT NULL",
    ),
    "test_cardinality.py::TestDjangoPrimaryKeyForeignKey.SRC": (
        ("fields.E007",),
        "ForeignKey(primary_key=True, null=True): erdify must still draw it NOT NULL",
    ),
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
    "test_django.py::TestDjangoMixinBases.test_unknown_base_is_still_read.src": (
        "a base imported from a module outside the source"
    ),
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
    reason = KNOWN_DIFFERENCES.get(name) or LIMITATIONS.get(name)
    if reason:
        marks.append(pytest.mark.xfail(reason=reason, raises=AssertionError, strict=True))
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
    _assert_checks(name, expected, ())
    _assert_same(_erdify(source, tmp_path), expected)


def _assert_checks(name: str, expected: Schema, allowed: tuple[str, ...], reason: str = "") -> None:
    """Fail unless Django's system checks report exactly the ``allowed`` errors.

    ``pytest.fail`` rather than ``assert``: a known-difference xfail only
    accepts an AssertionError, so a broken source must not hide behind one.
    """
    if expected.checks != allowed:
        pytest.fail(
            f"Django's system checks for {name} report {list(expected.checks) or 'no errors'}, "
            f"expected {list(allowed) or 'none'}"
            + (f" (listed: {reason})" if reason else "")
            + ". Fix the source (it must be a model module a Django project can run), "
            "or list a deliberate error in EXPECTED_CHECK_ERRORS."
        )


def _check(name: str, source: str, tmp_path: Path, *, catalog: bool = False) -> None:
    if name in DEGENERATE:
        pytest.skip(DEGENERATE[name])
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
    allowed, reason = ((), "") if catalog else EXPECTED_CHECK_ERRORS.get(name, ((), ""))
    _assert_checks(name, expected, allowed, reason)
    _assert_same(_erdify(source, tmp_path), expected)


@pytest.mark.parametrize("snippet", [_param(s.id, s) for s in SNIPPETS])
def test_snippet_matches_django(snippet: Snippet, tmp_path: Path) -> None:
    _check(snippet.id, snippet.source, tmp_path)


@pytest.mark.parametrize("path", [_param(p.stem, p) for p in EDGE_CASES])
def test_edge_case_matches_django(path: Path, tmp_path: Path) -> None:
    _check(path.stem, path.read_text(encoding="utf-8"), tmp_path, catalog=True)


def test_known_lists_name_existing_snippets() -> None:
    """A renamed or deleted test must not leave a stale entry behind."""
    names = {s.id for s in SNIPPETS} | {p.stem for p in EDGE_CASES}
    listed = (
        set(KNOWN_DIFFERENCES)
        | set(LIMITATIONS)
        | set(DEGENERATE)
        | set(EXPECTED_CHECK_ERRORS)
        | set(EXPECTED_REJECTED)
        | set(EXPECTED_UNLOADABLE)
    )
    assert not listed - names


def test_most_sources_are_compared() -> None:
    """Guard the discovery and the lists: most sources must really be compared."""
    listed = set(DEGENERATE) | set(EXPECTED_REJECTED) | set(EXPECTED_UNLOADABLE)
    compared = [s for s in SNIPPETS if s.id not in listed]
    assert len(compared) >= 40
    assert len(EDGE_CASES) >= 15


def test_reference_reports_system_check_errors() -> None:
    """The harness itself: an invalid model is reported, a valid one is clean."""
    bad = django_ref.load(
        "from django.db import models\n\n\n"
        "class Item(models.Model):\n    name = models.CharField()\n"
    )
    assert bad.checks == ("fields.E120",)
    good = django_ref.load(
        "from django.db import models\n\n\n"
        "class Item(models.Model):\n    name = models.CharField(max_length=5)\n"
    )
    assert good.checks == ()


def test_reference_swaps_in_the_sources_user_model() -> None:
    """A source with its own user model runs like a project that configured it."""
    schema = django_ref.load(
        "from django.conf import settings\n"
        "from django.contrib.auth.models import AbstractUser\n"
        "from django.db import models\n\n\n"
        "class Member(AbstractUser):\n    pass\n\n\n"
        "class Order(models.Model):\n"
        "    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)\n"
    )
    assert schema.checks == ()
    assert schema.tables["Order"].columns["buyer_id"].fk == "gt_member.id"


OUTSIDE_LABELS = """
from django.db import models


class A(models.Model):
    class Meta:
        app_label = "sales"
        db_table = "same"


class B(models.Model):
    class Meta:
        app_label = "sales"
        db_table = "same"
"""

MIXED_LABELS = """
from django.db import models


class A(models.Model):
    class Meta:
        app_label = "sales"
        db_table = "same"


class B(models.Model):
    class Meta:
        db_table = "same"
"""

INVALID_USER = """
from django.contrib.auth.models import AbstractBaseUser
from django.db import models


class Account(AbstractBaseUser):
    email = models.EmailField()

    USERNAME_FIELD = "email"
"""


def test_reference_runs_cross_model_checks() -> None:
    """Checks spanning models run too: two managed models on one table."""
    shared = django_ref.load(
        "from django.db import models\n\n\n"
        "class A(models.Model):\n    class Meta:\n        db_table = 'same'\n\n\n"
        "class B(models.Model):\n    class Meta:\n        db_table = 'same'\n"
    )
    assert shared.checks == ("models.E028",)
    # Models of another app label are installed and checked together.
    assert django_ref.load(OUTSIDE_LABELS).checks == ("models.E028",)
    assert django_ref.load(MIXED_LABELS).checks == ("models.E028",)


def test_reference_runs_the_contrib_checks() -> None:
    """auth's user-model validation runs: a non-unique USERNAME_FIELD is auth.E003."""
    assert django_ref.load(INVALID_USER).checks == ("auth.E003",)


@pytest.mark.parametrize(
    ("bodies", "user"),
    [
        (["class Member(AbstractUser):\n    pass\n"], "Member"),
        (
            [
                "class Member(AbstractUser):\n    pass\n",
                "class Staff(Member):\n    class Meta:\n        proxy = True\n",
                "class Customer(Member):\n    pass\n",
            ],
            "Member",
        ),
        (
            [
                "class Base(AbstractBaseUser):\n    class Meta:\n        abstract = True\n",
                "class Account(Base):\n    pass\n",
            ],
            "Account",
        ),
        (
            ["class Member(AbstractUser):\n    pass\n", "class Admin(AbstractUser):\n    pass\n"],
            None,
        ),
        (["class Base(AbstractUser):\n    class Meta:\n        abstract = True\n"], None),
        (["class Plain(models.Model):\n    pass\n"], None),
    ],
    ids=["one", "proxy_and_child", "via_abstract_base", "two", "only_abstract", "none"],
)
def test_reference_finds_the_sources_user_model(bodies: list[str], user: str | None) -> None:
    import ast

    source = "\n\n".join(bodies)
    assert django_ref._user_model(ast.parse(source)) == user


USER_IN_OTHER_APP = """
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


class Member(AbstractUser):
    class Meta:
        app_label = "sales"


class Order(models.Model):
    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
"""

USER_VIA_GET_USER_MODEL = """
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractUser
from django.db import models


class Member(AbstractUser):
    pass


class Order(models.Model):
    buyer = models.ForeignKey(get_user_model(), on_delete=models.CASCADE)
"""


def test_reference_swaps_in_a_user_model_of_another_app() -> None:
    schema = django_ref.load(USER_IN_OTHER_APP)
    assert schema.checks == ()
    assert schema.tables["Order"].columns["buyer_id"].fk == "sales_member.id"


def test_reference_resolves_get_user_model_in_the_isolated_registry() -> None:
    schema = django_ref.load(USER_VIA_GET_USER_MODEL)
    assert schema.checks == ()
    assert schema.tables["Order"].columns["buyer_id"].fk == "gt_member.id"
