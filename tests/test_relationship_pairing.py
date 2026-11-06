"""Pairing the two sides of a relationship (#240) and drawing them as one edge (#239)."""

import json
from pathlib import Path

from erdify.config import EntityInfo, FieldInfo
from erdify.generator import generate_json, generate_mermaid
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
    author: Mapped["User"] = relationship(back_populates="posts")


class Tag(Base):
    __tablename__ = "tag"
    id: Mapped[int] = mapped_column(primary_key=True)
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


class TestExplicitPairing:
    """``back_populates`` pairs exactly where the guess would pair wrongly."""

    @staticmethod
    def _entities(explicit: bool) -> dict[str, EntityInfo]:
        post_inverse = {"editor": "edited_post", "author": "authored_posts"} if explicit else {}
        user_inverse = {"authored_posts": "author", "edited_post": "editor"} if explicit else {}
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
                ("User", "one", "author"),
                nullable=("editor",),
                inverse=post_inverse,
            ),
        }

    def test_guess_without_back_populates(self):
        # The guess pairs the first N:1 with the first 1:N, which here is wrong.
        assert _edges(generate_mermaid(self._entities(explicit=False))) == [
            'Post }o--o| User : "editor"',
            'Post |o--|| User : "author"',
        ]

    def test_back_populates_pairs_exactly(self):
        assert _edges(generate_mermaid(self._entities(explicit=True))) == [
            'Post |o--o| User : "editor"',  # with User.edited_post: 1:1, optional both ways
            'Post }o--|| User : "author"',  # with User.authored_posts: N:1
        ]

    def test_explicit_inverse_is_not_taken_by_the_guess(self):
        """A side naming another attribute is never folded into a guessed pair."""
        entities = {
            "User": _entity("User", ("Post", "many", "posts"), inverse={"posts": "missing"}),
            "Post": _entity("Post", ("User", "one", "user")),
        }
        assert _edges(generate_mermaid(entities)) == [
            'User ||--o{ Post : "posts"',
            'Post }o--|| User : "user"',
        ]

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
