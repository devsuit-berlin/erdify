"""The public edge model: the relationships erdify draws (#359)."""

import json
from pathlib import Path

import pytest

from erdify import (
    Edge,
    EdgeEnd,
    EntityInfo,
    FieldInfo,
    diagram_edges,
    generate_json,
    generate_mermaid,
    generate_plantuml,
    parse_models_directory,
)

ONE = EdgeEnd(optional=False, many=False)
ZERO_OR_ONE = EdgeEnd(optional=True, many=False)
MANY = EdgeEnd(optional=True, many=True)


def _parse(tmp_path: Path, source: str) -> dict[str, EntityInfo]:
    (tmp_path / "models.py").write_text(source, encoding="utf-8")
    entities, _ = parse_models_directory(tmp_path)
    return entities


def _summary(edges: list[Edge]) -> list[tuple[str, str, str, str, str]]:
    return [(e.from_entity, e.glyph, e.to_entity, e.label, e.kind) for e in edges]


class TestEdgeEnd:
    @pytest.mark.parametrize(
        ("end", "right", "left"),
        [
            (EdgeEnd(optional=False, many=False), "||", "||"),
            (EdgeEnd(optional=True, many=False), "o|", "|o"),
            (EdgeEnd(optional=True, many=True), "o{", "}o"),
            (EdgeEnd(optional=False, many=True), "|{", "}|"),
        ],
    )
    def test_tokens(self, end: EdgeEnd, right: str, left: str) -> None:
        assert (end.right_token, end.left_token) == (right, left)


SQLALCHEMY = """
from sqlalchemy import Column, ForeignKey, Integer, Table
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass
"""


class TestForeignKeys:
    def test_nullable_and_unique_columns(self, tmp_path: Path) -> None:
        entities = _parse(
            tmp_path,
            SQLALCHEMY
            + """
class User(Base):
    __tablename__ = "user"
    id: Mapped[int] = mapped_column(primary_key=True)


class Post(Base):
    __tablename__ = "post"
    id: Mapped[int] = mapped_column(primary_key=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    editor_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"))


class Profile(Base):
    __tablename__ = "profile"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), unique=True)
""",
        )

        edges = diagram_edges(entities)

        assert [(e.from_end, e.to_end) for e in edges] == [
            (MANY, ONE),  # author_id: N:1, required
            (MANY, ZERO_OR_ONE),  # editor_id: nullable
            (ZERO_OR_ONE, ONE),  # unique: 1:1
        ]
        assert _summary(edges) == [
            ("Post", "}o--||", "User", "author_id", "foreign_key"),
            ("Post", "}o--o|", "User", "editor_id", "foreign_key"),
            ("Profile", "|o--||", "User", "user_id", "foreign_key"),
        ]

    def test_self_reference(self, tmp_path: Path) -> None:
        entities = _parse(
            tmp_path,
            SQLALCHEMY
            + """
class Node(Base):
    __tablename__ = "node"
    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("node.id"))
""",
        )

        assert _summary(diagram_edges(entities)) == [
            ("Node", "}o--o|", "Node", "parent_id", "foreign_key")
        ]


class TestLinkTables:
    def test_binary_link_table_is_a_path_through_its_entity(self, tmp_path: Path) -> None:
        entities = _parse(
            tmp_path,
            SQLALCHEMY
            + """
class Post(Base):
    __tablename__ = "post"
    id: Mapped[int] = mapped_column(primary_key=True)


class Tag(Base):
    __tablename__ = "tag"
    id: Mapped[int] = mapped_column(primary_key=True)


post_tag = Table(
    "post_tag",
    Base.metadata,
    Column("post_id", Integer, ForeignKey("post.id"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tag.id"), primary_key=True),
)
""",
        )

        assert _summary(diagram_edges(entities)) == [
            ("Post", "||--o{", "post_tag", "post_id", "link_table"),
            ("post_tag", "}o--||", "Tag", "tag_id", "link_table"),
        ]

    def test_ternary_link_table_is_a_star(self) -> None:
        def table(name: str) -> EntityInfo:
            return EntityInfo(name, name, [FieldInfo("id", "int", is_primary_key=True)])

        def fk(name: str, target: str) -> FieldInfo:
            return FieldInfo(
                name, "int", is_primary_key=True, is_foreign_key=True, foreign_table=f"{target}.id"
            )

        link = EntityInfo(
            "grant",
            "grant",
            [fk("user_id", "user"), fk("role_id", "role"), fk("site_id", "site")],
            is_link_table=True,
        )
        entities = {e.name: e for e in (table("user"), table("role"), table("site"), link)}

        assert _summary(diagram_edges(entities)) == [
            ("user", "||--o{", "grant", "user_id", "link_table"),
            ("role", "||--o{", "grant", "role_id", "link_table"),
            ("site", "||--o{", "grant", "site_id", "link_table"),
        ]


PYDANTIC = """
from pydantic import BaseModel
"""


class TestDeclaredRelationships:
    def test_inverse_pair_is_one_edge(self, tmp_path: Path) -> None:
        entities = _parse(
            tmp_path,
            PYDANTIC
            + """
class User(BaseModel):
    posts: list["Post"]


class Post(BaseModel):
    user: User | None
""",
        )

        assert _summary(diagram_edges(entities)) == [
            ("Post", "}o--o|", "User", "user", "relationship")
        ]

    def test_fk_column_suppresses_the_mirroring_relationship(self, tmp_path: Path) -> None:
        entities = _parse(
            tmp_path,
            SQLALCHEMY
            + """
class User(Base):
    __tablename__ = "user"
    id: Mapped[int] = mapped_column(primary_key=True)
    authored: Mapped[list["Post"]] = relationship(back_populates="author")


class Post(Base):
    __tablename__ = "post"
    id: Mapped[int] = mapped_column(primary_key=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    author: Mapped["User"] = relationship(back_populates="authored")
""",
        )

        # The foreign key already connects the pair: the relationship mirrors it.
        assert _summary(diagram_edges(entities)) == [
            ("Post", "}o--||", "User", "author_id", "foreign_key")
        ]

    def test_back_populates_beats_the_name_guess(self) -> None:
        """Without back_populates, `author` would pair with `authored` by name."""
        user = EntityInfo(
            "User",
            "user",
            relationships=[("Post", "many", "authored"), ("Post", "many", "edited")],
            inverse_relationships={"authored": "editor", "edited": "author"},
        )
        post = EntityInfo(
            "Post",
            "post",
            relationships=[("User", "one", "author"), ("User", "one", "editor")],
            nullable_relationships=["editor"],
            inverse_relationships={"author": "edited", "editor": "authored"},
        )

        edges = diagram_edges({"User": user, "Post": post})

        # Kept side: Post (sorts first); each edge pairs the attributes back_populates names.
        assert _summary(edges) == [
            ("Post", "}o--||", "User", "author", "relationship"),
            ("Post", "}o--o|", "User", "editor", "relationship"),
        ]
        assert [e.from_end for e in edges] == [MANY, MANY]

    def test_identical_edges_appear_once(self) -> None:
        user = EntityInfo("User", "user")
        post = EntityInfo(
            "Post", "post", relationships=[("User", "one", "user"), ("User", "one", "user")]
        )

        assert _summary(diagram_edges({"User": user, "Post": post})) == [
            ("Post", "}o--||", "User", "user", "relationship")
        ]

    def test_self_reference_folds_parent_and_children(self, tmp_path: Path) -> None:
        entities = _parse(
            tmp_path,
            PYDANTIC
            + """
class Node(BaseModel):
    parent: "Node | None"
    children: list["Node"]
""",
        )

        assert _summary(diagram_edges(entities)) == [
            ("Node", "|o--o{", "Node", "children", "relationship")
        ]

    def test_missing_target_is_skipped(self) -> None:
        user = EntityInfo("User", "user", relationships=[("Gone", "many", "posts")])

        assert diagram_edges({"User": user}) == []

    def test_endpoints_are_entity_names_when_keys_differ(self) -> None:
        user = EntityInfo("User", "user")
        post = EntityInfo("Post", "post", relationships=[("users", "one", "user")])

        edges = diagram_edges({"users": user, "posts": post})

        assert _summary(edges) == [("Post", "}o--||", "User", "user", "relationship")]


class TestRenderers:
    def test_plantuml_and_mermaid_draw_exactly_the_edges(self, tmp_path: Path) -> None:
        entities = _parse(
            tmp_path,
            PYDANTIC
            + """
class User(BaseModel):
    posts: list["Post"]


class Post(BaseModel):
    user: User
""",
        )
        lines = [f"{e.from_entity} {e.glyph} {e.to_entity}" for e in diagram_edges(entities)]

        assert lines == ["Post }o--|| User"]
        assert 'Post }o--|| User : "user"' in generate_plantuml(entities, {})
        assert 'Post }o--|| User : "user"' in generate_mermaid(entities, {})


class TestJson:
    def test_json_lists_the_edges(self, tmp_path: Path) -> None:
        entities = _parse(
            tmp_path,
            PYDANTIC + 'class User(BaseModel):\n    best_friend: "User | None"\n',
        )

        document = json.loads(generate_json(entities, {}))

        assert document["edges"] == [
            {
                "from_entity": "User",
                "to_entity": "User",
                "from_end": {"optional": True, "many": True},
                "to_end": {"optional": True, "many": False},
                "label": "best_friend",
                "kind": "relationship",
            }
        ]

    def test_no_relationships_means_no_edges(self, tmp_path: Path) -> None:
        entities = _parse(
            tmp_path,
            PYDANTIC + 'class User(BaseModel):\n    best_friend: "User | None"\n',
        )

        document = json.loads(generate_json(entities, {}, include_relationships=False))

        assert document["edges"] == []
