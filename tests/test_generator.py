"""Tests for generator module."""

import json
from pathlib import Path

import pytest

from erdify.generator import (
    PlantUMLGenerator,
    generate_html,
    generate_json,
    generate_mermaid,
    generate_plantuml,
)
from erdify.parser import parse_models_directory
from erdify.config import EntityInfo, FieldInfo


class TestPlantUMLGenerator:
    """Tests for PlantUMLGenerator class."""

    def test_generate_basic_diagram(self, sample_models_dir: Path):
        """Test generating a basic diagram."""
        entities, enums = parse_models_directory(sample_models_dir)
        generator = PlantUMLGenerator(entities, enums)
        output = generator.generate()

        # Check structure
        assert "@startuml" in output
        assert "@enduml" in output

    def test_generate_with_custom_title(self, sample_models_dir: Path):
        """Test generating a diagram with custom title."""
        entities, enums = parse_models_directory(sample_models_dir)
        generator = PlantUMLGenerator(entities, enums, title="My Custom ERD")
        output = generator.generate()

        assert "@startuml My Custom ERD" in output

    def test_generate_entities(self, sample_models_dir: Path):
        """Test that entities are included in output."""
        entities, enums = parse_models_directory(sample_models_dir)
        generator = PlantUMLGenerator(entities, enums)
        output = generator.generate()

        # Check entities are present
        assert 'entity "user" as User' in output
        assert 'entity "product" as Product' in output
        assert 'entity "order" as Order' in output

    def test_generate_enums(self, sample_models_dir: Path):
        """Test that enums are included in output."""
        entities, enums = parse_models_directory(sample_models_dir)
        generator = PlantUMLGenerator(entities, enums)
        output = generator.generate()

        # Check enums section
        assert "' Enums" in output

    def test_generate_relationships(self, sample_models_dir: Path):
        """Test that relationships are included in output."""
        entities, enums = parse_models_directory(sample_models_dir)
        generator = PlantUMLGenerator(entities, enums)
        output = generator.generate()

        # Check relationships section
        assert "' Relationships" in output
        # Order has FK to User
        assert "Order" in output and "User" in output

    def test_generate_link_table_styling(self, sample_models_dir: Path):
        """Test that link tables have special styling."""
        entities, enums = parse_models_directory(sample_models_dir)
        generator = PlantUMLGenerator(entities, enums)
        output = generator.generate()

        # Link tables should have special marker
        assert "link >>" in output

    def test_generate_primary_key_formatting(self):
        """Test primary key field formatting."""
        entities = {
            "User": EntityInfo(
                name="User",
                table_name="user",
                fields=[
                    FieldInfo(name="id", type_str="int", is_primary_key=True),
                ],
            )
        }
        generator = PlantUMLGenerator(entities)
        output = generator.generate()

        assert "primary_key(id)" in output

    def test_generate_foreign_key_formatting(self):
        """Test foreign key field formatting."""
        entities = {
            "Order": EntityInfo(
                name="Order",
                table_name="order",
                fields=[
                    FieldInfo(
                        name="user_id",
                        type_str="int",
                        is_foreign_key=True,
                        foreign_table="user.id",
                    ),
                ],
            )
        }
        generator = PlantUMLGenerator(entities)
        output = generator.generate()

        assert "foreign_key(user_id)" in output

    def test_generate_nullable_field_marker(self):
        """Test nullable fields have ? marker."""
        entities = {
            "Product": EntityInfo(
                name="Product",
                table_name="product",
                fields=[
                    FieldInfo(name="description", type_str="str", is_nullable=True),
                ],
            )
        }
        generator = PlantUMLGenerator(entities)
        output = generator.generate()

        assert "str?" in output

    def test_generate_default_value(self):
        """Test fields with default values."""
        entities = {
            "User": EntityInfo(
                name="User",
                table_name="user",
                fields=[
                    FieldInfo(name="is_active", type_str="bool", default_value="True"),
                ],
            )
        }
        generator = PlantUMLGenerator(entities)
        output = generator.generate()

        assert "= True" in output


class TestRelationshipRendering:
    """Tests for drawing relationships from entity.relationships (keyless sources)."""

    def _rel_lines(self, output: str) -> list[str]:
        """Return only the relationship/arrow lines from the output."""
        return [line for line in output.splitlines() if "--" in line and ":" in line]

    def test_pydantic_relationship_is_drawn(self, pydantic_models_dir: Path):
        """Nested-ref relationships (no FK) still produce a relationship line."""
        entities, enums = parse_models_directory(pydantic_models_dir)
        output = generate_plantuml(entities, enums)

        rel_lines = self._rel_lines(output)
        customer_invoice = [line for line in rel_lines if "Customer" in line and "Invoice" in line]
        assert customer_invoice, "expected a Customer<->Invoice relationship line"

    def test_pydantic_relationship_not_duplicated(self, pydantic_models_dir: Path):
        """A bidirectional nested ref yields exactly one line per entity pair."""
        entities, enums = parse_models_directory(pydantic_models_dir)
        output = generate_plantuml(entities, enums)

        rel_lines = self._rel_lines(output)
        customer_invoice = [line for line in rel_lines if "Customer" in line and "Invoice" in line]
        assert len(customer_invoice) == 1

    def test_sqlmodel_relationship_not_doubled_by_relationship_list(self, sample_models_dir: Path):
        """SQLModel FK line must not be duplicated by the relationship-list rendering."""
        entities, enums = parse_models_directory(sample_models_dir)
        output = generate_plantuml(entities, enums)

        rel_lines = self._rel_lines(output)
        order_user = [line for line in rel_lines if "Order " in line and " User" in line]
        # Exactly the single FK-derived line: Order }o--|| User : "user_id"
        assert len(order_user) == 1

    def test_dataclass_relationship_is_drawn(self, dataclass_models_dir: Path):
        """Dataclass nested refs produce a relationship line."""
        entities, enums = parse_models_directory(dataclass_models_dir)
        output = generate_plantuml(entities, enums)

        rel_lines = self._rel_lines(output)
        warehouse_item = [line for line in rel_lines if "Warehouse" in line and "Item" in line]
        assert len(warehouse_item) == 1


class TestGeneratePlantuml:
    """Tests for generate_plantuml convenience function."""

    def test_generate_plantuml_basic(self, sample_models_dir: Path):
        """Test the convenience function."""
        entities, enums = parse_models_directory(sample_models_dir)
        output = generate_plantuml(entities, enums)

        assert "@startuml" in output
        assert "@enduml" in output

    def test_generate_plantuml_custom_title(self, sample_models_dir: Path):
        """Test with custom title."""
        entities, enums = parse_models_directory(sample_models_dir)
        output = generate_plantuml(entities, enums, title="Test ERD")

        assert "@startuml Test ERD" in output

    def test_generate_plantuml_no_enums(self, sample_models_dir: Path):
        """Test with enums disabled."""
        entities, enums = parse_models_directory(sample_models_dir)
        output = generate_plantuml(entities, enums, include_enums=False)

        # Should not have enum definitions
        # Note: the "' Enums" comment may still be there but no enum blocks
        assert "enum UserRole" not in output

    def test_generate_plantuml_empty_entities(self):
        """Test with no entities."""
        output = generate_plantuml({}, {})

        assert "@startuml" in output
        assert "@enduml" in output
        assert "' Entities" in output


def test_json_includes_unique_flag():
    entities = {
        "profile": EntityInfo(
            name="profile",
            table_name="profile",
            fields=[FieldInfo(name="email", type_str="str", is_unique=True)],
        )
    }
    model = json.loads(generate_json(entities))
    field = model["entities"][0]["fields"][0]
    assert field["unique"] is True


def _direct_rel_lines(child_field):
    entities = {
        "child": EntityInfo(
            name="child",
            table_name="child",
            fields=[FieldInfo(name="id", type_str="int", is_primary_key=True), child_field],
        ),
        "parent": EntityInfo(
            name="parent",
            table_name="parent",
            fields=[FieldInfo(name="id", type_str="int", is_primary_key=True)],
        ),
    }
    return generate_mermaid(entities)


def test_unique_notnull_fk_renders_one_to_one():
    fk = FieldInfo(
        name="parent_id",
        type_str="int",
        is_foreign_key=True,
        foreign_table="parent.id",
        is_unique=True,
        is_nullable=False,
    )
    # child end |o (a parent has zero-or-one child), parent end || (NOT NULL FK).
    assert "child |o--|| parent" in _direct_rel_lines(fk)


def test_unique_nullable_fk_renders_zero_or_one_to_one():
    fk = FieldInfo(
        name="parent_id",
        type_str="int",
        is_foreign_key=True,
        foreign_table="parent.id",
        is_unique=True,
        is_nullable=True,
    )
    # child end |o (zero-or-one child), parent end o| (nullable FK).
    assert "child |o--o| parent" in _direct_rel_lines(fk)


def test_non_unique_fk_still_renders_many_to_one():
    fk = FieldInfo(
        name="parent_id",
        type_str="int",
        is_foreign_key=True,
        foreign_table="parent.id",
        is_unique=False,
    )
    assert "child }o--|| parent" in _direct_rel_lines(fk)


def test_nullable_non_unique_fk_renders_optional_parent():
    """A nullable FK means the child may have no parent: parent end is o| (#216)."""
    fk = FieldInfo(
        name="parent_id",
        type_str="int",
        is_foreign_key=True,
        foreign_table="parent.id",
        is_nullable=True,
    )
    assert "child }o--o| parent" in _direct_rel_lines(fk)


def test_mermaid_unique_column_shows_uk():
    entities = {
        "profile": EntityInfo(
            name="profile",
            table_name="profile",
            fields=[
                FieldInfo(name="id", type_str="int", is_primary_key=True),
                FieldInfo(
                    name="customer_id",
                    type_str="int",
                    is_foreign_key=True,
                    foreign_table="customer.id",
                    is_unique=True,
                ),
                FieldInfo(name="email", type_str="str", is_unique=True),
            ],
        ),
        "customer": EntityInfo(
            name="customer",
            table_name="customer",
            fields=[FieldInfo(name="id", type_str="int", is_primary_key=True)],
        ),
    }
    out = generate_mermaid(entities)
    assert "int customer_id FK,UK" in out
    assert "str email UK" in out
    assert "int id PK\n" in out or "int id PK " in out  # PK not tagged UK


def test_plantuml_unique_column_shows_uk():
    entities = {
        "profile": EntityInfo(
            name="profile",
            table_name="profile",
            fields=[FieldInfo(name="email", type_str="varchar", is_unique=True)],
        ),
    }
    out = generate_plantuml(entities)
    assert "column(email) : varchar UK" in out


def test_mermaid_composite_pk_fk_column_uses_comma_no_space():
    """Lock the Mermaid multi-key separator: ``PK,FK`` with no space."""
    entities = {
        "order_item": EntityInfo(
            name="order_item",
            table_name="order_item",
            fields=[
                FieldInfo(
                    name="order_id",
                    type_str="int",
                    is_primary_key=True,
                    is_foreign_key=True,
                    foreign_table="order.id",
                ),
                FieldInfo(name="line_no", type_str="int", is_primary_key=True),
            ],
        ),
        "order": EntityInfo(
            name="order",
            table_name="order",
            fields=[FieldInfo(name="id", type_str="int", is_primary_key=True)],
        ),
    }
    out = generate_mermaid(entities)
    assert "int order_id PK,FK" in out
    assert "PK, FK" not in out


def test_plantuml_pk_and_unique_omits_uk():
    """A column that is both primary key AND unique must not get a ` UK` suffix."""
    entities = {
        "profile": EntityInfo(
            name="profile",
            table_name="profile",
            fields=[FieldInfo(name="id", type_str="varchar", is_primary_key=True, is_unique=True)],
        ),
    }
    out = generate_plantuml(entities)
    assert "primary_key(id) : varchar" in out
    assert "UK" not in out


def test_declared_relationship_glyphs():
    """Hand-built IR: every declared relationship type, incl. an optional "one" (#223)."""
    entities = {
        "A": EntityInfo(
            name="A",
            table_name="a",
            relationships=[
                ("B", "one_to_one", "b"),
                ("C", "one", "c"),
                ("D", "one", "d"),
                ("E", "many", "es"),
            ],
            nullable_relationships=["d"],
        ),
        **{n: EntityInfo(name=n, table_name=n.lower()) for n in "BCDE"},
    }
    out = generate_mermaid(entities)
    assert 'A ||--|| B : "b"' in out
    assert 'A }o--|| C : "c"' in out
    assert 'A }o--o| D : "d"' in out
    assert 'A ||--o{ E : "es"' in out


def test_json_nullable_only_for_one():
    """A hand-built flag on a non-"one" relationship is ignored, as in the diagram."""
    entities = {
        "A": EntityInfo(
            name="A",
            table_name="a",
            relationships=[("B", "one", "b"), ("B", "one_to_one", "c"), ("B", "many", "ds")],
            nullable_relationships=["b", "c", "ds"],
        ),
        "B": EntityInfo(name="B", table_name="b"),
    }
    doc = json.loads(generate_json(entities))
    rels = doc["entities"][0]["relationships"]
    assert {r["attribute"]: r["nullable"] for r in rels} == {"b": True, "c": False, "ds": False}


def _edges(output: str) -> list[str]:
    """The relationship lines of a PlantUML or Mermaid diagram, stripped."""
    return [line.strip() for line in output.splitlines() if "--" in line and " : " in line]


def _entity(name: str, *relationships: tuple[str, str, str], nullable: tuple[str, ...] = ()):
    return EntityInfo(
        name=name,
        table_name=name.lower(),
        fields=[FieldInfo(name="id", type_str="int", is_primary_key=True)],
        relationships=list(relationships),
        source="pydantic",
        nullable_relationships=list(nullable),
    )


class TestNoRelationships:
    """``include_relationships=False`` hides every edge in every format (#232)."""

    @staticmethod
    def _entities() -> dict[str, EntityInfo]:
        user = EntityInfo(
            name="User",
            table_name="user",
            fields=[FieldInfo(name="id", type_str="int", is_primary_key=True)],
        )
        group = EntityInfo(
            name="Group",
            table_name="group",
            fields=[FieldInfo(name="id", type_str="int", is_primary_key=True)],
        )
        post = EntityInfo(
            name="Post",
            table_name="post",
            fields=[
                FieldInfo(name="id", type_str="int", is_primary_key=True),
                FieldInfo(
                    name="user_id", type_str="int", is_foreign_key=True, foreign_table="user.id"
                ),
            ],
            relationships=[("Group", "one_to_one", "group")],
        )
        link = EntityInfo(
            name="UserGroup",
            table_name="user_group",
            fields=[
                FieldInfo(
                    name="user_id",
                    type_str="int",
                    is_primary_key=True,
                    is_foreign_key=True,
                    foreign_table="user.id",
                ),
                FieldInfo(
                    name="group_id",
                    type_str="int",
                    is_primary_key=True,
                    is_foreign_key=True,
                    foreign_table="group.id",
                ),
            ],
            is_link_table=True,
        )
        return {e.name: e for e in (user, group, post, link)}

    @pytest.mark.parametrize("generate", [generate_plantuml, generate_mermaid, generate_html])
    def test_edges_drawn_by_default(self, generate):
        """Sanity check: the fixture has FK, link-table and declared edges."""
        assert len(_edges(generate(self._entities()))) == 4

    @pytest.mark.parametrize("generate", [generate_plantuml, generate_mermaid, generate_html])
    def test_no_edges_when_disabled(self, generate):
        output = generate(self._entities(), include_relationships=False)
        assert _edges(output) == []
        # The entities themselves are still rendered.
        assert "Post" in output and "UserGroup" in output

    def test_plantuml_omits_relationships_section(self):
        output = generate_plantuml(self._entities(), include_relationships=False)
        assert "' Relationships" not in output


class TestDistinctReferencesToSameModel:
    """Several declared references to one model each get an edge (#230)."""

    def test_two_references_from_one_model(self):
        entities = {
            "User": _entity("User"),
            "Post": _entity(
                "Post", ("User", "one", "user"), ("User", "one", "author"), nullable=("user",)
            ),
        }
        assert _edges(generate_mermaid(entities)) == [
            'Post }o--o| User : "user"',
            'Post }o--|| User : "author"',
        ]

    def test_bidirectional_pair_drawn_once(self):
        entities = {
            "User": _entity("User", ("Post", "many", "posts")),
            "Post": _entity("Post", ("User", "one", "user")),
        }
        assert _edges(generate_mermaid(entities)) == ['User ||--o{ Post : "posts"']

    def test_extra_reference_beside_bidirectional_pair(self):
        """The inverse side absorbs one reference; the other one is still drawn."""
        entities = {
            "User": _entity("User", ("Post", "many", "posts")),
            "Post": _entity("Post", ("User", "one", "author"), ("User", "one", "user")),
        }
        assert _edges(generate_mermaid(entities)) == [
            'User ||--o{ Post : "posts"',
            'Post }o--|| User : "author"',
        ]

    def test_inverse_prefers_matching_cardinality(self):
        """A 1:N side pairs with an N:1 reference before a 1:1 one."""
        entities = {
            "User": _entity("User", ("Profile", "many", "profiles")),
            "Profile": _entity("Profile", ("User", "one_to_one", "owner"), ("User", "one", "user")),
        }
        assert _edges(generate_mermaid(entities)) == [
            'User ||--o{ Profile : "profiles"',
            'Profile ||--|| User : "owner"',
        ]

    def test_self_reference_parent_children_drawn_once(self):
        entities = {
            "Node": _entity(
                "Node",
                ("Node", "one", "parent"),
                ("Node", "many", "children"),
                nullable=("parent",),
            ),
        }
        assert _edges(generate_mermaid(entities)) == ['Node }o--o| Node : "parent"']

    def test_self_reference_extra_reference_drawn(self):
        entities = {
            "Node": _entity(
                "Node",
                ("Node", "one", "parent"),
                ("Node", "many", "children"),
                ("Node", "one", "owner"),
                nullable=("parent",),
            ),
        }
        assert _edges(generate_mermaid(entities)) == [
            'Node }o--o| Node : "parent"',
            'Node }o--|| Node : "owner"',
        ]

    def test_foreign_key_pair_still_skips_declared_relationships(self):
        user = _entity("User")
        post = _entity("Post", ("User", "one", "user"), ("User", "one", "author"))
        post.fields.append(
            FieldInfo(name="user_id", type_str="int", is_foreign_key=True, foreign_table="user.id")
        )
        entities = {"User": user, "Post": post}
        assert _edges(generate_mermaid(entities)) == ['Post }o--|| User : "user_id"']

    def test_self_reference_same_cardinality_stays_two_edges(self):
        entities = {
            "Employee": _entity(
                "Employee", ("Employee", "one", "manager"), ("Employee", "one", "mentor")
            ),
        }
        assert _edges(generate_mermaid(entities)) == [
            'Employee }o--|| Employee : "manager"',
            'Employee }o--|| Employee : "mentor"',
        ]

    def test_inverse_without_matching_cardinality_still_collapsed(self):
        """Two N:1 references pointing at each other are one 1:1 edge, as before."""
        entities = {
            "User": _entity("User", ("Account", "one", "account")),
            "Account": _entity("Account", ("User", "one", "owner")),
        }
        assert _edges(generate_mermaid(entities)) == ['User }o--|| Account : "account"']

    def test_inverse_named_after_acronym_class(self):
        """``HTTPRequest`` is referenced as ``http_request``, not ``h_t_t_p_request``."""
        entities = {
            "HTTPRequest": _entity("HTTPRequest", ("Header", "many", "headers")),
            "Header": _entity(
                "Header", ("HTTPRequest", "one", "origin"), ("HTTPRequest", "one", "http_request")
            ),
        }
        assert _edges(generate_mermaid(entities)) == [
            'HTTPRequest ||--o{ Header : "headers"',
            'Header }o--|| HTTPRequest : "origin"',
        ]

    def test_reference_side_declared_first(self):
        """With the N:1 model first, its references are kept and the 1:N side folds."""
        entities = {
            "Post": _entity("Post", ("User", "one", "user"), ("User", "one", "author")),
            "User": _entity("User", ("Post", "many", "posts")),
        }
        assert _edges(generate_mermaid(entities)) == [
            'Post }o--|| User : "user"',
            'Post }o--|| User : "author"',
        ]

    def test_bidirectional_pair_beside_foreign_key_pair(self):
        user = _entity("User", ("Post", "many", "posts"))
        post = _entity("Post", ("User", "one", "user"))
        comment = _entity("Comment")
        comment.fields.append(
            FieldInfo(name="post_id", type_str="int", is_foreign_key=True, foreign_table="post.id")
        )
        entities = {"User": user, "Post": post, "Comment": comment}
        assert _edges(generate_mermaid(entities)) == [
            'Comment }o--|| Post : "post_id"',
            'User ||--o{ Post : "posts"',
        ]

    @pytest.mark.parametrize("kind", ["many_to_many", "one_to_one"])
    def test_self_reference_symmetric_kind_stays_two_edges(self, kind: str):
        """``ManyToManyField("self")`` twice: independent, not each other's inverse."""
        entities = {
            "User": _entity("User", ("User", kind, "friends"), ("User", kind, "blocked")),
        }
        assert [e.split(" : ")[1] for e in _edges(generate_mermaid(entities))] == [
            '"friends"',
            '"blocked"',
        ]
