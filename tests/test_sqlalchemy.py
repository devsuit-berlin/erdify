"""Tests for parsing SQLAlchemy 2.0 (Mapped/mapped_column) models."""

from pathlib import Path

from erdify.parser import parse_models_directory


class TestSQLAlchemyParsing:
    """Tests for SQLAlchemy 2.0 (Mapped/mapped_column) model parsing."""

    def test_parse_entities(self, sqlalchemy_models_dir: Path):
        """Mapped classes with __tablename__ are detected as entities."""
        entities, _ = parse_models_directory(sqlalchemy_models_dir)

        assert "Author" in entities
        assert "Post" in entities
        assert "Tag" in entities
        assert "PostTagLink" in entities

    def test_entities_have_sqlalchemy_source(self, sqlalchemy_models_dir: Path):
        """Parsed SQLAlchemy tables are tagged with source 'sqlalchemy'."""
        entities, _ = parse_models_directory(sqlalchemy_models_dir)
        assert entities["Author"].source == "sqlalchemy"

    def test_declarative_base_not_an_entity(self, sqlalchemy_models_dir: Path):
        """The DeclarativeBase subclass itself is not a table."""
        entities, _ = parse_models_directory(sqlalchemy_models_dir)
        assert "Base" not in entities

    def test_mixin_not_an_entity_but_fields_inherited(self, sqlalchemy_models_dir: Path):
        """A mixin without __tablename__ is not a table, but its fields are inherited."""
        entities, _ = parse_models_directory(sqlalchemy_models_dir)

        assert "TimestampMixin" not in entities
        author_fields = {f.name for f in entities["Author"].fields}
        assert "created_at" in author_fields
        assert "updated_at" in author_fields

    def test_parse_table_names(self, sqlalchemy_models_dir: Path):
        """Table names come from __tablename__."""
        entities, _ = parse_models_directory(sqlalchemy_models_dir)
        assert entities["Author"].table_name == "author"
        assert entities["Post"].table_name == "post"

    def test_parse_primary_key(self, sqlalchemy_models_dir: Path):
        """primary_key=True on mapped_column is detected."""
        entities, _ = parse_models_directory(sqlalchemy_models_dir)
        author_fields = {f.name: f for f in entities["Author"].fields}
        assert author_fields["id"].is_primary_key is True
        assert author_fields["name"].is_primary_key is False

    def test_parse_foreign_key(self, sqlalchemy_models_dir: Path):
        """ForeignKey() inside mapped_column is detected."""
        entities, _ = parse_models_directory(sqlalchemy_models_dir)
        post_fields = {f.name: f for f in entities["Post"].fields}
        assert post_fields["author_id"].is_foreign_key is True
        assert post_fields["author_id"].foreign_table == "author.id"

    def test_parse_mapped_type_unwrapped(self, sqlalchemy_models_dir: Path):
        """Mapped[X] annotations are unwrapped to X."""
        entities, _ = parse_models_directory(sqlalchemy_models_dir)
        author_fields = {f.name: f for f in entities["Author"].fields}
        assert author_fields["id"].type_str == "int"
        assert author_fields["name"].type_str == "str"

    def test_parse_nullable_optional(self, sqlalchemy_models_dir: Path):
        """Mapped[Optional[str]] and Mapped[str | None] are nullable."""
        entities, _ = parse_models_directory(sqlalchemy_models_dir)
        author_fields = {f.name: f for f in entities["Author"].fields}
        post_fields = {f.name: f for f in entities["Post"].fields}
        assert author_fields["bio"].is_nullable is True
        assert author_fields["name"].is_nullable is False
        assert post_fields["summary"].is_nullable is True

    def test_parse_index(self, sqlalchemy_models_dir: Path):
        """index=True on mapped_column is detected."""
        entities, _ = parse_models_directory(sqlalchemy_models_dir)
        author_fields = {f.name: f for f in entities["Author"].fields}
        assert author_fields["email"].index is True
        assert author_fields["name"].index is False

    def test_parse_relationship(self, sqlalchemy_models_dir: Path):
        """Lowercase relationship() with Mapped[list[...]] is parsed."""
        entities, _ = parse_models_directory(sqlalchemy_models_dir)
        author_rels = {r[2]: r for r in entities["Author"].relationships}
        assert "posts" in author_rels
        assert author_rels["posts"][0] == "Post"
        assert author_rels["posts"][1] == "many"

    def test_relationship_not_treated_as_field(self, sqlalchemy_models_dir: Path):
        """A relationship attribute must not appear as a column field."""
        entities, _ = parse_models_directory(sqlalchemy_models_dir)
        author_field_names = {f.name for f in entities["Author"].fields}
        assert "posts" not in author_field_names

    def test_parse_enum(self, sqlalchemy_models_dir: Path):
        """Enums are still detected alongside SQLAlchemy models."""
        _, enums = parse_models_directory(sqlalchemy_models_dir)
        assert "PostStatus" in enums
        assert "DRAFT" in enums["PostStatus"].values

    def test_link_table_detected(self, sqlalchemy_models_dir: Path):
        """Link tables are detected by name heuristic."""
        entities, _ = parse_models_directory(sqlalchemy_models_dir)
        assert entities["PostTagLink"].is_link_table is True
