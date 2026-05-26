"""Tests for parser module."""

from pathlib import Path

from erdify.parser import ASTDatabaseParser, parse_models_directory


class TestASTDatabaseParser:
    """Tests for ASTDatabaseParser class."""

    def test_parse_entities(self, sample_models_dir: Path):
        """Test parsing entities from models."""
        parser = ASTDatabaseParser(sample_models_dir)
        entities, enums = parser.parse_all_models()

        # Check entities were found
        assert "User" in entities
        assert "Product" in entities
        assert "Order" in entities
        assert "OrderItem" in entities
        assert "UserProductLink" in entities

    def test_parse_enums(self, sample_models_dir: Path):
        """Test parsing enums from models."""
        parser = ASTDatabaseParser(sample_models_dir)
        entities, enums = parser.parse_all_models()

        # Check enums were found
        assert "UserRole" in enums
        assert "OrderStatus" in enums

        # Check enum values
        assert "ADMIN" in enums["UserRole"].values
        assert "USER" in enums["UserRole"].values
        assert "GUEST" in enums["UserRole"].values

        assert "PENDING" in enums["OrderStatus"].values
        assert "COMPLETED" in enums["OrderStatus"].values
        assert "PROCESSING" in enums["OrderStatus"].values
        assert "CANCELLED" in enums["OrderStatus"].values

    def test_parse_table_names(self, sample_models_dir: Path):
        """Test that table names are correctly parsed."""
        parser = ASTDatabaseParser(sample_models_dir)
        entities, _ = parser.parse_all_models()

        assert entities["User"].table_name == "user"
        assert entities["Product"].table_name == "product"
        assert entities["Order"].table_name == "order"
        assert entities["OrderItem"].table_name == "order_item"

    def test_parse_primary_keys(self, sample_models_dir: Path):
        """Test that primary keys are correctly identified."""
        parser = ASTDatabaseParser(sample_models_dir)
        entities, _ = parser.parse_all_models()

        user_fields = {f.name: f for f in entities["User"].fields}
        assert user_fields["id"].is_primary_key is True
        assert user_fields["name"].is_primary_key is False

    def test_parse_foreign_keys(self, sample_models_dir: Path):
        """Test that foreign keys are correctly identified."""
        parser = ASTDatabaseParser(sample_models_dir)
        entities, _ = parser.parse_all_models()

        order_fields = {f.name: f for f in entities["Order"].fields}
        assert order_fields["user_id"].is_foreign_key is True
        assert order_fields["user_id"].foreign_table == "user.id"

    def test_parse_link_table(self, sample_models_dir: Path):
        """Test that link tables are correctly identified."""
        parser = ASTDatabaseParser(sample_models_dir)
        entities, _ = parser.parse_all_models()

        assert entities["UserProductLink"].is_link_table is True
        assert entities["User"].is_link_table is False

    def test_parse_nullable_fields(self, sample_models_dir: Path):
        """Test that nullable fields are correctly identified."""
        parser = ASTDatabaseParser(sample_models_dir)
        entities, _ = parser.parse_all_models()

        product_fields = {f.name: f for f in entities["Product"].fields}
        assert product_fields["description"].is_nullable is True
        assert product_fields["name"].is_nullable is False

    def test_parse_indexed_fields(self, sample_models_dir: Path):
        """Test that indexed fields are correctly identified."""
        parser = ASTDatabaseParser(sample_models_dir)
        entities, _ = parser.parse_all_models()

        user_fields = {f.name: f for f in entities["User"].fields}
        assert user_fields["email"].index is True
        assert user_fields["name"].index is False

    def test_parse_relationships(self, sample_models_dir: Path):
        """Test that relationships are correctly parsed."""
        parser = ASTDatabaseParser(sample_models_dir)
        entities, _ = parser.parse_all_models()

        # User has many Orders
        user_rels = {r[2]: r for r in entities["User"].relationships}
        assert "orders" in user_rels
        assert user_rels["orders"][0] == "Order"  # target
        assert user_rels["orders"][1] == "many"  # type

    def test_parse_empty_models(self, empty_models_dir: Path):
        """Test parsing an empty models file."""
        parser = ASTDatabaseParser(empty_models_dir)
        entities, enums = parser.parse_all_models()

        assert len(entities) == 0
        assert len(enums) == 0

    def test_parse_inheritance(self, models_with_inheritance_dir: Path):
        """Test parsing models with inheritance."""
        parser = ASTDatabaseParser(models_with_inheritance_dir)
        entities, _ = parser.parse_all_models()

        # Article should have inherited fields
        assert "Article" in entities
        article_fields = {f.name: f for f in entities["Article"].fields}

        # Should have own fields
        assert "title" in article_fields
        assert "content" in article_fields

        # Should have inherited fields from BaseEntity and TimestampMixin
        assert "id" in article_fields
        assert "created_at" in article_fields
        assert "updated_at" in article_fields


class TestParseModelsDirectory:
    """Tests for parse_models_directory convenience function."""

    def test_parse_models_directory(self, sample_models_dir: Path):
        """Test the convenience function."""
        entities, enums = parse_models_directory(sample_models_dir)

        assert len(entities) > 0
        assert len(enums) > 0
        assert "User" in entities
        assert "UserRole" in enums

    def test_parse_nonexistent_directory(self, temp_dir: Path):
        """Test parsing a directory with no models.py files."""
        entities, enums = parse_models_directory(temp_dir)
        assert len(entities) == 0
        assert len(enums) == 0
