"""Ground truth: erdify's SQLAlchemy / SQLModel parse must match what SQLAlchemy builds (#265).

Every SQLAlchemy and SQLModel model source the suite uses (the fixtures, the
docs examples, the edge-case catalog in ``fixtures/sqlalchemy_edge_cases`` and
the inline snippets of the regression tests) is loaded twice: parsed by erdify
from text, and executed as a module, with its mappers configured. Both are
reduced to the same normalised schema (tables, columns, primary / unique /
foreign keys, nullability, declared relationships with their cardinality,
optionality and ``back_populates``, enums) and must agree.

Configuring the mappers is SQLAlchemy's own validation of the models (what
``configure_mappers()`` does on first use): a source whose relationships can't
be set up (an ambiguous join, a ``back_populates`` naming nothing) is test data
no project could run, and fails unless ``EXPECTED_CHECK_ERRORS`` lists it.

Nothing is skipped silently: known differences, documented limitations,
sources SQLAlchemy rejects and sources that are not self-contained are each
listed below with a reason. A strict ``xfail`` turns into a failure once its
issue is fixed, an unlisted rejection or skip fails, and a listed name that no
longer exists fails.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlmodel

from tests.ground_truth import sqlalchemy_ref
from tests.ground_truth.schema import Schema, from_erdify
from tests.ground_truth.snippets import Snippet, sqlalchemy_snippets

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
SOURCES = ("sqlalchemy", "sqlmodel")

MODULES = {
    **{
        f"fixtures/{name}": FIXTURES / name
        for name in (
            "sqlalchemy",
            "ecommerce",
            "edge_cases",
            "inheritance",
            "link_detection",
            "m2m_link_model",
            "m2m_secondary",
            "m2m_secondary_table",
        )
    },
    "docs/examples/sqlalchemy": ROOT / "docs" / "examples" / "sqlalchemy",
    "docs/examples/sqlmodel": ROOT / "docs" / "examples" / "sqlmodel",
}

EDGE_CASES_DIR = FIXTURES / "sqlalchemy_edge_cases"
EDGE_CASES = sorted(EDGE_CASES_DIR.glob("*.py"))

# Test helpers that prepend a module-level header to the bodies they get.
SNIPPET_HEADERS = {"test_annotated_metadata.py": "HEADER"}

# erdify output that differs from SQLAlchemy's schema, pending a fix.
KNOWN_DIFFERENCES = {
    # SQLModel's default table name is the lower-cased class name.
    "fixtures/m2m_link_model": "#291: SQLModel default table name is cls.__name__.lower()",
    "fixtures/edge_cases": "#291: SQLModel default table name is cls.__name__.lower()",
    "sqlmodel_basics": "#291: SQLModel default table name is cls.__name__.lower()",
    "test_cardinality.py::TestSharedPrimaryKey.SRC": (
        "#291: SQLModel default table name is cls.__name__.lower()"
    ),
    # An explicit column name names the column.
    "column_names": "#292: mapped_column('name') / name= names the column",
    "sqlmodel_sa_column": "#292: sa_column=Column('name') / sa_column_kwargs name the column",
    "test_cardinality.py::TestExplicitColumnName.test_inherited_column_name.src": (
        "#292: mapped_column('name') names the column"
    ),
    "test_inheritance.py::TestBasePrecedence.test_explicit_column_name_follows_mro.src": (
        "#292: mapped_column('name') names the column"
    ),
    "joined_inheritance": "#293: a joined-table subclass has only its own table's columns",
    "single_table_inheritance": "#302: single-table subclass columns belong to the parent table",
    "mapped_as_dataclass": "#294: `x: Mapped[T] = value` is not a column",
    "test_annotated_metadata.py::test_assigned_plain_default_wins_over_metadata.entities": (
        "#294: `x: Mapped[T] = value` is not a column"
    ),
    "enums": "#296: enum.IntEnum (and other Enum subclasses) are not drawn as enums",
    "imperative_table": "#297: a class mapped with __table__ = Table(...) is not drawn",
    "mixins": "#298: a relationship from a @declared_attr on a mixin is not read",
    "one_to_one_required_reverse": (
        "#299: a to-one reference from the referenced side is always optional"
    ),
    "test_ground_truth_sqlalchemy.py"
    "::test_reference_leaves_out_created_and_inherited_relationships.schema": (
        "#293: a joined-table subclass has only its own table's columns"
    ),
    "test_inheritance.py::TestInconsistentHierarchy.test_self_named_base.src": (
        "#300: a model extending an earlier class of the same name inherits its fields"
    ),
}

# The oldest supported SQLModel is 0.0.22 (docs/installation.md); CI runs these
# tests on it and on the locked release. Where SQLModel itself changed, the
# expected schema depends on the installed version.
SQLMODEL_VERSION = tuple(int(part) for part in sqlmodel.__version__.split(".")[:3])

# Catalog modules for a SQLModel feature, skipped before the release that added it.
REQUIRES_SQLMODEL = {
    "sqlmodel_annotated_field": ((0, 0, 32), "Field() in Annotated metadata"),
}

# Known differences that exist only from a SQLModel release on (before it,
# erdify matches SQLModel): name -> (release, reason).
SQLMODEL_DIFFERENCES = {
    "sqlmodel_annotated_field": (
        (0, 0, 32),
        "#295: SQLModel 0.0.32+ applies Field() from Annotated metadata",
    ),
    "test_annotated_metadata.py::TestMergeLikeSqlAlchemy"
    ".test_sqlmodel_field_in_metadata_is_ignored": (
        (0, 0, 32),
        "#295: SQLModel 0.0.32+ applies Field() from Annotated metadata",
    ),
}

# Documented in docs/frameworks/limitations.md; strict xfails, so that the
# page is updated once one is supported.
LIMITATIONS = {
    "classic_columns": "limitations.md: classic Column() attributes are not read",
    "composite_foreign_key": "limitations.md: composite foreign keys are not read",
    "schema_qualified": "limitations.md: schema= is ignored",
    # SQLALCHEMY_TABLE_ARGS puts one model in a schema ("app").
    "test_cardinality.py::SQLALCHEMY_TABLE_ARGS": "limitations.md: schema= is ignored",
    "test_cardinality.py::TestNullableForeignKey.test_explicit_nullable_overrides_annotation"
    ".src": "limitations.md: schema= is ignored",
    "test_cardinality.py::TestNullableForeignKey.test_nullable_none_keeps_annotation.src": (
        "limitations.md: schema= is ignored"
    ),
    "bare_relationship": "limitations.md: relationships need an annotation",
    "sqlmodel_sa_column_foreign_key": "limitations.md: foreign keys hidden in sa_column",
    "test_column_annotations.py::TestSqlAlchemyDetection"
    ".test_classic_column_only_class_not_detected.source": (
        "limitations.md: classic Column() attributes are not read"
    ),
}

# Inline snippets whose mappers don't configure on purpose: error class names
# and why. Every other source must configure, and the fixtures, the docs
# examples and the edge-case catalog always must.
EXPECTED_CHECK_ERRORS = {
    "test_ground_truth_sqlalchemy.py::test_reference_reports_configuration_errors.schema": (
        ("NoForeignKeysError",),
        "the harness's own test that configuration errors are reported",
    ),
}

# Sources SQLAlchemy refuses to map that the suite still feeds to erdify on
# purpose, as robustness tests.
EXPECTED_REJECTED = {
    "test_annotated_metadata.py::TestTypeAliases.test_self_referencing_alias_does_not_loop"
    ".entities": "an alias defined in terms of itself; erdify must not loop",
    "test_annotated_metadata.py::TestModuleScope._two_files": (
        "a class head the test completes with a column from another file"
    ),
    "test_annotated_metadata.py::TestPythonScoping._model": (
        "a class head the test completes with a column from another file"
    ),
    "test_cardinality.py::TestExplicitColumnName.test_subclass_override_drops_inherited_name.src": (
        "a constraint on a column name the subclass override removed; erdify must not keep it"
    ),
    "test_inheritance.py::TestInconsistentHierarchy.test_falls_back_without_crashing.src": (
        "bases with no consistent MRO; erdify must not crash"
    ),
    "test_ground_truth_sqlalchemy.py::test_reference_rejects_a_table_without_primary_key": (
        "the harness's own test of a rejected source"
    ),
    "test_relationship_pairing.py::TestParserSpellings.MIXIN": (
        "relationship() on a plain mixin needs @declared_attr (#298)"
    ),
    "test_model_references.py::TestRedeclaration"
    ".test_unresolvable_redeclaration_shadows_the_inherited_relationship.src": (
        "relationship() on a plain mixin needs @declared_attr (#298)"
    ),
}

# Sources that are not a self-contained model module, so there is nothing to
# load them into. Each is a deliberate test of erdify on partial input.
STRING_METADATA = "string metadata in Annotated[...]: SQLAlchemy reads it as a forward reference"
OTHER_FILE = "an alias from another file of the test"
COMPLETED = "a source the test completes with a parameter"
TEMPLATE = "a str.format template"
EXPECTED_UNLOADABLE = {
    "test_annotated_metadata.py::TestInlineAnnotated.test_other_metadata_is_ignored"
    ".entities": STRING_METADATA,
    "test_annotated_metadata.py::TestCopilotRound2.test_nested_annotated_alias"
    ".entities": STRING_METADATA,
    "test_annotated_metadata.py::TestModuleScope.test_derived_alias_in_the_same_module"
    ".entities": STRING_METADATA,
    "test_annotated_metadata.py::TestCopilotPr253"
    ".test_alias_rebinding_itself_uses_the_earlier_binding.entities": STRING_METADATA,
    "test_annotated_metadata.py::TestTypeAliases"
    ".test_alias_defined_in_another_scanned_file": OTHER_FILE,
    "test_annotated_metadata.py::TestAliasScope"
    ".test_conflicting_definitions_are_not_used": OTHER_FILE,
    "test_annotated_metadata.py::TestCopilotRound1"
    ".test_import_of_the_alias_itself_keeps_it": OTHER_FILE,
    "test_annotated_metadata.py::TestModuleScopeEdges._model": COMPLETED,
    "test_annotated_metadata.py::TestPythonScoping"
    ".test_mixin_in_another_module_uses_its_own_aliases[2]": (
        "a mixin from another file of the test"
    ),
    "test_annotated_metadata.py::test_mutual_imports_do_not_loop": OTHER_FILE,
    "test_annotated_metadata.py::TestCopilotPr253.test_last_all_assignment_counts": OTHER_FILE,
    "test_annotated_metadata.py::TestCopilotPr253"
    ".test_resolved_alias_is_not_re_expanded_at_the_use_site": OTHER_FILE,
    "test_annotated_metadata.py::TestCopilotPr253Round3"
    ".test_package_shadows_same_named_module": OTHER_FILE,
    "test_annotated_metadata.py::TestFallbackFixedPoint"
    ".test_derived_alias_through_an_ambiguous_import": OTHER_FILE,
    "test_annotated_metadata.py::TestFallbackFixedPoint"
    ".test_chain_of_fallback_dependencies": OTHER_FILE,
    "test_annotated_metadata.py::TestFallbackFixedPoint.test_long_chain_is_not_cut_off": OTHER_FILE,
    "test_annotated_metadata.py::TestFallbackFixedPoint"
    ".test_conflicting_cycle_is_deterministic": OTHER_FILE,
    "test_annotated_metadata.py::TestFallbackFixedPoint"
    ".test_conflicting_cycle_through_an_explicit_import": OTHER_FILE,
    "test_annotated_metadata.py::TestFallbackFixedPoint"
    ".test_re_exports_of_an_ambiguous_alias": OTHER_FILE,
    "test_annotated_metadata.py::TestFallbackFixedPoint"
    ".test_ambiguous_import_of_a_class_name_is_not_an_alias": OTHER_FILE,
    "test_annotated_metadata"
    ".py::test_self_referencing_definition_that_differs_conflicts": OTHER_FILE,
    "test_annotated_metadata.py::TestModuleScope.test_mutually_recursive_aliases_do_not_loop"
    ".entities": "aliases defined in terms of each other; erdify must not loop",
    "test_cardinality.py::TestTableArgsForms.BASE": TEMPLATE,
    "test_cardinality.py::TestExplicitColumnName.SRC": TEMPLATE,
    "test_column_annotations.py::SQLALCHEMY": TEMPLATE,
    "test_model_references.py::SQLALCHEMY": TEMPLATE,
    "test_model_references.py::SQLMODEL": TEMPLATE,
    "test_dialects.py::test_classify_before_parsing"
    ".node": "one class for a classification unit test, no imports",
    **{
        "test_ground_truth_sqlalchemy.py::test_reference_reports_sources_that_are_not_self_contained"
        + suffix: "the harness's own test of a source that is not self-contained"
        for suffix in ("", "[2]", "[3]")
    },
}

SNIPPETS = sqlalchemy_snippets(SNIPPET_HEADERS)


def _param(name: str, value: object) -> object:
    marks = []
    reason = KNOWN_DIFFERENCES.get(name) or LIMITATIONS.get(name)
    since, sqlmodel_reason = SQLMODEL_DIFFERENCES.get(name, ((), ""))
    if not reason and since and SQLMODEL_VERSION >= since:
        reason = sqlmodel_reason
    if reason:
        marks.append(pytest.mark.xfail(reason=reason, raises=AssertionError, strict=True))
    required, feature = REQUIRES_SQLMODEL.get(name, ((), ""))
    if required and SQLMODEL_VERSION < required:
        release = ".".join(map(str, required))
        marks.append(pytest.mark.skip(reason=f"{feature} needs SQLModel {release}+"))
    return pytest.param(value, id=name, marks=marks)


def _assert_same(actual: Schema, expected: Schema) -> None:
    assert actual.tables == expected.tables
    assert actual.enums == expected.enums


def _erdify(source: str, tmp_path: Path, *, relationships: bool = True) -> Schema:
    (tmp_path / "models.py").write_text(source, encoding="utf-8")
    return from_erdify(tmp_path, SOURCES, relationships=relationships)


def _assert_checks(name: str, expected: Schema, allowed: tuple[str, ...], reason: str = "") -> None:
    """Fail unless configuring the mappers reports exactly the ``allowed`` errors.

    ``pytest.fail`` rather than ``assert``: a known-difference xfail only
    accepts an AssertionError, so a broken source must not hide behind one.
    """
    if expected.checks != allowed:
        pytest.fail(
            f"Configuring the mappers of {name} reports {list(expected.checks) or 'no errors'}, "
            f"expected {list(allowed) or 'none'}"
            + (f" (listed: {reason})" if reason else "")
            + ". Fix the source (it must be a model module a project can run), "
            "or list a deliberate error in EXPECTED_CHECK_ERRORS."
        )


def _check(name: str, source: str, tmp_path: Path, *, strict: bool = False) -> None:
    """Compare erdify with SQLAlchemy for one source.

    ``strict`` sources (fixtures, docs examples, the catalog) must load and
    configure; the lists only apply to inline snippets.
    """
    try:
        expected = sqlalchemy_ref.load(source)
    except sqlalchemy_ref.Rejected as exc:
        if name in EXPECTED_REJECTED and not strict:
            pytest.skip(f"SQLAlchemy rejects this source ({EXPECTED_REJECTED[name]}): {exc}")
        pytest.fail(
            f"SQLAlchemy rejects {name}: {exc}. Fix the source, or list it in "
            "EXPECTED_REJECTED if it is a deliberate robustness test."
        )
    except sqlalchemy_ref.Unloadable as exc:
        if name in EXPECTED_UNLOADABLE and not strict:
            pytest.skip(f"not a self-contained model module ({EXPECTED_UNLOADABLE[name]})")
        pytest.fail(f"Cannot load {name}: {exc}. Fix it or list it in EXPECTED_UNLOADABLE.")
    allowed, reason = ((), "") if strict else EXPECTED_CHECK_ERRORS.get(name, ((), ""))
    _assert_checks(name, expected, allowed, reason)
    # Without configured mappers there are no relationships to compare.
    _assert_same(_erdify(source, tmp_path, relationships=not expected.checks), expected)


@pytest.mark.parametrize("name", [_param(n, n) for n in sorted(MODULES)])
def test_module_matches_sqlalchemy(name: str, tmp_path: Path) -> None:
    source = (MODULES[name] / "models.py").read_text(encoding="utf-8")
    _check(name, source, tmp_path, strict=True)


@pytest.mark.parametrize("path", [_param(p.stem, p) for p in EDGE_CASES])
def test_edge_case_matches_sqlalchemy(path: Path, tmp_path: Path) -> None:
    _check(path.stem, path.read_text(encoding="utf-8"), tmp_path, strict=True)


@pytest.mark.parametrize("snippet", [_param(s.id, s) for s in SNIPPETS])
def test_snippet_matches_sqlalchemy(snippet: Snippet, tmp_path: Path) -> None:
    _check(snippet.id, snippet.source, tmp_path)


def test_known_lists_name_existing_sources() -> None:
    """A renamed or deleted test must not leave a stale entry behind."""
    names = {s.id for s in SNIPPETS} | {p.stem for p in EDGE_CASES} | set(MODULES)
    listed = (
        set(KNOWN_DIFFERENCES)
        | set(SQLMODEL_DIFFERENCES)
        | set(REQUIRES_SQLMODEL)
        | set(LIMITATIONS)
        | set(EXPECTED_CHECK_ERRORS)
        | set(EXPECTED_REJECTED)
        | set(EXPECTED_UNLOADABLE)
    )
    assert not listed - names


def test_most_sources_are_compared() -> None:
    """Guard the discovery and the lists: most sources must really be compared."""
    listed = set(EXPECTED_REJECTED) | set(EXPECTED_UNLOADABLE)
    compared = [s for s in SNIPPETS if s.id not in listed]
    assert len(compared) >= 40
    assert len(EDGE_CASES) >= 25


def test_reference_reports_configuration_errors() -> None:
    """The harness itself: a relationship with no foreign key fails to configure."""
    schema = sqlalchemy_ref.load(
        "from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship\n\n\n"
        "class Base(DeclarativeBase):\n    pass\n\n\n"
        "class A(Base):\n    __tablename__ = 'a'\n"
        "    id: Mapped[int] = mapped_column(primary_key=True)\n"
        "    bs: Mapped[list['B']] = relationship()\n\n\n"
        "class B(Base):\n    __tablename__ = 'b'\n"
        "    id: Mapped[int] = mapped_column(primary_key=True)\n"
    )
    assert schema.checks == ("NoForeignKeysError",)


def test_reference_rejects_a_table_without_primary_key() -> None:
    with pytest.raises(sqlalchemy_ref.Rejected):
        sqlalchemy_ref.load(
            "from sqlalchemy.orm import DeclarativeBase, Mapped\n\n\n"
            "class Base(DeclarativeBase):\n    pass\n\n\n"
            "class A(Base):\n    __tablename__ = 'a'\n    name: Mapped[str]\n"
        )


@pytest.mark.parametrize(
    "source",
    [
        "from sqlalchemy import Column, ForeignKey, Table\n"
        "from sqlalchemy.orm import DeclarativeBase\n\n\n"
        "class Base(DeclarativeBase):\n    pass\n\n\n"
        "link = Table('link', Base.metadata,\n"
        "    Column('a_id', ForeignKey('a.id'), primary_key=True),\n"
        "    Column('b_id', ForeignKey('b.id'), primary_key=True))\n",
        "from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship\n\n\n"
        "class Base(DeclarativeBase):\n    pass\n\n\n"
        "class A(Base):\n    __tablename__ = 'a'\n"
        "    id: Mapped[int] = mapped_column(primary_key=True)\n"
        "    other: Mapped['Other'] = relationship()\n",
        "from sqlmodel import SQLModel\n\n\nclass A(Unknown, table=True):\n    pass\n",
    ],
    ids=["foreign_key_target", "relationship_target", "name"],
)
def test_reference_reports_sources_that_are_not_self_contained(source: str) -> None:
    with pytest.raises(sqlalchemy_ref.Unloadable) as raised:
        sqlalchemy_ref.load(source)
    assert type(raised.value) is sqlalchemy_ref.Unloadable


SQLMODEL_HERO = """
from sqlmodel import Field, SQLModel


class Hero(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
"""


def test_reference_isolates_sqlmodel_metadata() -> None:
    """SQLModel's shared registry is swapped per load: the same table loads twice."""
    first = sqlalchemy_ref.load(SQLMODEL_HERO)
    assert sqlalchemy_ref.load(SQLMODEL_HERO) == first
    assert first.tables["Hero"].table == "hero"
    from sqlmodel import SQLModel

    assert "hero" not in SQLModel.metadata.tables


def test_reference_runs_sources_without_the_harness_future_imports() -> None:
    """The source's own annotations are evaluated, not the harness's string ones."""
    schema = sqlalchemy_ref.load(
        "from sqlmodel import Field, Relationship, SQLModel\n\n\n"
        "class Team(SQLModel, table=True):\n"
        "    id: int | None = Field(default=None, primary_key=True)\n"
        "    heroes: list['Hero'] = Relationship(back_populates='team')\n\n\n"
        "class Hero(SQLModel, table=True):\n"
        "    id: int | None = Field(default=None, primary_key=True)\n"
        "    team_id: int | None = Field(default=None, foreign_key='team.id')\n"
        "    team: Team | None = Relationship(back_populates='heroes')\n"
    )
    assert schema.checks == ()
    assert schema.tables["Team"].relationships["heroes"].kind == "many"


def test_reference_leaves_out_created_and_inherited_relationships() -> None:
    """A backref= side isn't declared, and a mapped parent's relationship is the parent's."""
    schema = sqlalchemy_ref.load(
        "from sqlalchemy import ForeignKey\n"
        "from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship\n\n\n"
        "class Base(DeclarativeBase):\n    pass\n\n\n"
        "class Owner(Base):\n    __tablename__ = 'owner'\n"
        "    id: Mapped[int] = mapped_column(primary_key=True)\n\n\n"
        "class Pet(Base):\n    __tablename__ = 'pet'\n"
        "    id: Mapped[int] = mapped_column(primary_key=True)\n"
        "    kind: Mapped[str]\n"
        "    owner_id: Mapped[int] = mapped_column(ForeignKey('owner.id'))\n"
        "    owner: Mapped[Owner] = relationship(backref='pets')\n"
        "    __mapper_args__ = {'polymorphic_on': 'kind', 'polymorphic_identity': 'pet'}\n\n\n"
        "class Dog(Pet):\n    __tablename__ = 'dog'\n"
        "    id: Mapped[int] = mapped_column(ForeignKey('pet.id'), primary_key=True)\n"
        "    __mapper_args__ = {'polymorphic_identity': 'dog'}\n"
    )
    assert schema.tables["Owner"].relationships == {}
    assert set(schema.tables["Pet"].relationships) == {"owner"}
    assert schema.tables["Pet"].relationships["owner"].inverse is None
    assert schema.tables["Dog"].relationships == {}
