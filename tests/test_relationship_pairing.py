"""Pairing the two sides of a relationship (#240) and drawing them as one edge (#239)."""

import json
from pathlib import Path

from erdify.config import EntityInfo, FieldInfo
from erdify.generator import generate_json, generate_mermaid, generate_plantuml
from erdify.parser import parse_models_directory


def _edges(output: str) -> list[str]:
    return [line.strip() for line in output.splitlines() if "--" in line and " : " in line]


def _entity(
    name: str,
    *relationships: tuple[str, str, str],
    nullable: tuple[str, ...] = (),
    inverse: dict[str, str] | None = None,
) -> EntityInfo:
    return EntityInfo(
        name=name,
        table_name=name.lower(),
        fields=[FieldInfo(name="id", type_str="int", is_primary_key=True)],
        relationships=list(relationships),
        source="sqlalchemy",
        nullable_relationships=list(nullable),
        inverse_relationships=inverse or {},
    )


class TestParserRecordsInverse:
    SRC = """
from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "user"
    id: Mapped[int] = mapped_column(primary_key=True)
    posts: Mapped[list["Post"]] = relationship(back_populates="author")
    tags: Mapped[list["Tag"]] = relationship(backref="owner")


class Post(Base):
    __tablename__ = "post"
    id: Mapped[int] = mapped_column(primary_key=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    author: Mapped["User"] = relationship(back_populates="posts")


class Tag(Base):
    __tablename__ = "tag"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
"""

    def test_back_populates_is_recorded(self, tmp_path: Path):
        (tmp_path / "models.py").write_text(self.SRC, encoding="utf-8")
        entities, _ = parse_models_directory(tmp_path)
        assert entities["User"].inverse_relationships == {"posts": "author"}
        assert entities["Post"].inverse_relationships == {"author": "posts"}

    def test_json_exposes_inverse(self, tmp_path: Path):
        (tmp_path / "models.py").write_text(self.SRC, encoding="utf-8")
        entities, _ = parse_models_directory(tmp_path)
        doc = json.loads(generate_json(entities))
        rels = {
            (e["name"], r["attribute"]): r["inverse"]
            for e in doc["entities"]
            for r in e["relationships"]
        }
        assert rels == {
            ("User", "posts"): "author",
            ("User", "tags"): None,  # backref= declares no second side
            ("Post", "author"): "posts",
        }

    def test_excluded_target_drops_inverse(self, tmp_path: Path):
        (tmp_path / "models.py").write_text(self.SRC, encoding="utf-8")
        entities, _ = parse_models_directory(tmp_path, exclude_patterns=["Post"])
        assert entities["User"].inverse_relationships == {}


class TestParserSpellings:
    def _parse(self, tmp_path: Path, src: str) -> dict[str, EntityInfo]:
        (tmp_path / "models.py").write_text(src, encoding="utf-8")
        entities, _ = parse_models_directory(tmp_path)
        return entities

    def test_sqlmodel_back_populates_both_forms(self, tmp_path: Path):
        entities = self._parse(
            tmp_path,
            """
from sqlmodel import Field, Relationship, SQLModel


class Team(SQLModel, table=True):
    id: int = Field(primary_key=True)
    heroes: list["Hero"] = Relationship(
        back_populates="team", sa_relationship_kwargs={"foreign_keys": "[Hero.team_id]"}
    )
    leaders: list["Hero"] = Relationship(
        sa_relationship_kwargs={"back_populates": "led", "foreign_keys": "[Hero.led_id]"}
    )


class Hero(SQLModel, table=True):
    id: int = Field(primary_key=True)
    team_id: int = Field(foreign_key="team.id")
    team: "Team" = Relationship(
        back_populates="heroes", sa_relationship_kwargs={"foreign_keys": "[Hero.team_id]"}
    )
    led_id: int = Field(foreign_key="team.id")
    led: "Team" = Relationship(sa_relationship_kwargs={"foreign_keys": "[Hero.led_id]"})
""",
        )
        assert entities["Team"].inverse_relationships == {"heroes": "team", "leaders": "led"}
        assert entities["Hero"].inverse_relationships == {"team": "heroes"}

    MIXIN = """
from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class AuthoredMixin:
    author_id: Mapped[int] = mapped_column(ForeignKey("user.id"))

    @declared_attr
    def author(cls) -> Mapped["User"]:
        return relationship(back_populates="posts")


class User(Base):
    __tablename__ = "user"
    id: Mapped[int] = mapped_column(primary_key=True)
    posts: Mapped[list["Post"]] = relationship(back_populates="author")


class Post(AuthoredMixin, Base):
    __tablename__ = "post"
    id: Mapped[int] = mapped_column(primary_key=True)


class Draft(AuthoredMixin, Base):
    __tablename__ = "draft"
    id: Mapped[int] = mapped_column(primary_key=True)
    author: Mapped["User"] = relationship()
"""

    def test_mixin_carries_back_populates(self, tmp_path: Path):
        assert self._parse(tmp_path, self.MIXIN)["Post"].inverse_relationships == {
            "author": "posts"
        }

    def test_redeclaration_without_back_populates_drops_it(self, tmp_path: Path):
        assert self._parse(tmp_path, self.MIXIN)["Draft"].inverse_relationships == {}


class TestExplicitPairing:
    """``back_populates`` pairs exactly where the guess would pair wrongly."""

    @staticmethod
    def _entities(explicit: bool) -> dict[str, EntityInfo]:
        post_inverse = {"editor": "edited_post", "writer": "authored_posts"} if explicit else {}
        user_inverse = {"authored_posts": "writer", "edited_post": "editor"} if explicit else {}
        return {
            "User": _entity(
                "User",
                ("Post", "many", "authored_posts"),
                ("Post", "one", "edited_post"),
                nullable=("edited_post",),
                inverse=user_inverse,
            ),
            "Post": _entity(
                "Post",
                ("User", "one", "editor"),
                ("User", "one", "writer"),
                nullable=("editor",),
                inverse=post_inverse,
            ),
        }

    def test_guess_without_back_populates(self):
        # The guess pairs the N:1 sorting first with the 1:N, which here is wrong.
        assert _edges(generate_mermaid(self._entities(explicit=False))) == [
            'Post }o--o| User : "editor"',
            'Post |o--|| User : "writer"',
        ]

    def test_back_populates_pairs_exactly(self):
        assert _edges(generate_mermaid(self._entities(explicit=True))) == [
            'Post |o--o| User : "editor"',  # with User.edited_post: 1:1, optional both ways
            'Post }o--|| User : "writer"',  # with User.authored_posts: N:1
        ]

    def test_inverse_naming_a_missing_attribute_is_guessed(self):
        """A stale or misspelled back_populates falls back to the guess."""
        entities = {
            "User": _entity("User", ("Post", "many", "posts"), inverse={"posts": "writer"}),
            "Post": _entity("Post", ("User", "one", "user")),
        }
        assert _edges(generate_mermaid(entities)) == ['Post }o--|| User : "user"']

    def test_inverse_naming_a_taken_attribute_is_not_guessed(self):
        """Two sides claiming the same partner: the mutual one wins, the other stays alone."""
        entities = {
            "A": _entity(
                "A",
                ("B", "many", "x"),
                ("B", "many", "x2"),
                inverse={"x": "y", "x2": "y"},
            ),
            "B": _entity("B", ("A", "one", "y"), nullable=("y",), inverse={"y": "x2"}),
        }
        expected = [
            'A ||--o{ B : "x"',  # its partner is taken: drawn alone, not guessed
            'A |o--o{ B : "x2"',  # mutual with B.y (optional)
        ]
        assert _edges(generate_mermaid(entities)) == expected
        reordered = {"B": entities["B"], "A": entities["A"]}
        assert _edges(generate_mermaid(reordered)) == expected

    def test_self_reference_back_populates(self):
        entities = {
            "Node": _entity(
                "Node",
                ("Node", "many", "children"),
                ("Node", "one", "parent"),
                ("Node", "one", "owner"),
                nullable=("parent",),
                inverse={"children": "parent", "parent": "children"},
            ),
        }
        assert _edges(generate_mermaid(entities)) == [
            'Node |o--o{ Node : "children"',
            'Node }o--|| Node : "owner"',
        ]


class TestMergedEnds:
    """Each end of a folded edge shows what its own side declares (#239)."""

    def test_list_on_both_sides_is_many_to_many(self):
        entities = {
            "A": _entity("A", ("B", "many", "tags")),
            "B": _entity("B", ("A", "many", "items")),
        }
        assert _edges(generate_mermaid(entities)) == ['A }o--o{ B : "tags"']

    def test_optional_reference_stays_optional(self):
        entities = {
            "User": _entity("User", ("Post", "many", "posts")),
            "Post": _entity("Post", ("User", "one", "user"), nullable=("user",)),
        }
        assert _edges(generate_mermaid(entities)) == ['Post }o--o| User : "user"']

    def test_independent_of_entity_order(self):
        user = _entity("User", ("Post", "many", "posts"))
        post = _entity("Post", ("User", "one", "user"), nullable=("user",))
        forward = _edges(generate_mermaid({"User": user, "Post": post}))
        backward = _edges(generate_mermaid({"Post": post, "User": user}))
        assert forward == backward == ['Post }o--o| User : "user"']


class TestMoreSpellings:
    def test_one_sided_back_populates(self):
        entities = {
            "User": _entity("User", ("Post", "many", "items"), inverse={"items": "owner"}),
            "Post": _entity("Post", ("User", "one", "owner"), ("User", "one", "user")),
        }
        # Without back_populates the guess would fold `user` (named after User).
        assert _edges(generate_mermaid(entities)) == [
            'Post }o--|| User : "owner"',
            'Post }o--|| User : "user"',
        ]
        out = generate_mermaid(entities)
        assert 'User ||--o{ Post : "items"' not in out

    def test_self_reference_guess_is_independent_of_declaration_order(self):
        def node(*rels: tuple[str, str, str]) -> dict[str, EntityInfo]:
            return {"Node": _entity("Node", *rels, nullable=("parent",))}

        children_first = node(("Node", "many", "children"), ("Node", "one", "parent"))
        parent_first = node(("Node", "one", "parent"), ("Node", "many", "children"))
        assert (
            _edges(generate_mermaid(children_first))
            == _edges(generate_mermaid(parent_first))
            == ['Node |o--o{ Node : "children"']
        )

    def test_irregular_plural_counts_as_named(self):
        """``Product.categories`` is named after ``Category``: it wins over ``archived``."""
        entities = {
            "Category": _entity("Category", ("Product", "one", "product")),
            "Product": _entity(
                "Product",
                ("Category", "many", "archived"),
                ("Category", "many", "categories"),
            ),
        }
        assert _edges(generate_mermaid(entities)) == [
            'Category }o--|| Product : "product"',  # folded with Product.categories
            'Product ||--o{ Category : "archived"',
        ]

    def test_nullable_non_one_kinds_do_not_crash(self):
        """A hand-built IR may list any attribute as nullable; only `one` uses it."""
        entities = {
            "A": _entity("A", ("B", "one_to_one", "b"), nullable=("b",)),
            "B": _entity("B", ("A", "many", "a"), nullable=("a",)),
        }
        assert _edges(generate_mermaid(entities)) == ['A }o--|| B : "b"']

    def test_plantuml_uses_the_same_merged_edges(self):
        entities = {
            "A": _entity("A", ("B", "many", "tags")),
            "B": _entity("B", ("A", "many", "items")),
            "Post": _entity("Post", ("User", "one", "user"), nullable=("user",)),
            "User": _entity("User", ("Post", "many", "posts"), ("Post", "one", "pinned")),
        }
        out = generate_plantuml(entities)
        assert 'A }o--o{ B : "tags"' in out
        assert 'Post }o--o| User : "user"' in out
