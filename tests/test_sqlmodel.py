"""Tests for parsing SQLModel models (Field/Relationship, table=True)."""

from pathlib import Path

from erdify.parser import ASTDatabaseParser, parse_models_directory


class TestSQLModelParsing:
    """Tests for SQLModel model parsing."""

    def test_parse_entities(self, sample_models_dir: Path):
        """Test parsing entities from models."""
        parser = ASTDatabaseParser(sample_models_dir)
        entities, _ = parser.parse_all_models()

        assert "User" in entities
        assert "Product" in entities
        assert "Order" in entities
        assert "OrderItem" in entities
        assert "UserProductLink" in entities

    def test_entities_have_sqlmodel_source(self, sample_models_dir: Path):
        """Parsed SQLModel tables are tagged with source 'sqlmodel'."""
        entities, _ = parse_models_directory(sample_models_dir)
        assert entities["User"].source == "sqlmodel"

    def test_parse_enums(self, sample_models_dir: Path):
        """Test parsing enums from models."""
        _, enums = parse_models_directory(sample_models_dir)

        assert "UserRole" in enums
        assert "OrderStatus" in enums

        assert "ADMIN" in enums["UserRole"].values
        assert "USER" in enums["UserRole"].values
        assert "GUEST" in enums["UserRole"].values

        assert "PENDING" in enums["OrderStatus"].values
        assert "COMPLETED" in enums["OrderStatus"].values

    def test_parse_table_names(self, sample_models_dir: Path):
        """Test that table names are correctly parsed."""
        entities, _ = parse_models_directory(sample_models_dir)

        assert entities["User"].table_name == "user"
        assert entities["Product"].table_name == "product"
        assert entities["Order"].table_name == "order"
        assert entities["OrderItem"].table_name == "order_item"

    def test_parse_primary_keys(self, sample_models_dir: Path):
        """Test that primary keys are correctly identified."""
        entities, _ = parse_models_directory(sample_models_dir)

        user_fields = {f.name: f for f in entities["User"].fields}
        assert user_fields["id"].is_primary_key is True
        assert user_fields["name"].is_primary_key is False

    def test_parse_foreign_keys(self, sample_models_dir: Path):
        """Test that foreign keys are correctly identified."""
        entities, _ = parse_models_directory(sample_models_dir)

        order_fields = {f.name: f for f in entities["Order"].fields}
        assert order_fields["user_id"].is_foreign_key is True
        assert order_fields["user_id"].foreign_table == "user.id"

    def test_parse_link_table(self, sample_models_dir: Path):
        """Test that link tables are correctly identified."""
        entities, _ = parse_models_directory(sample_models_dir)

        assert entities["UserProductLink"].is_link_table is True
        assert entities["User"].is_link_table is False

    def test_parse_nullable_fields(self, sample_models_dir: Path):
        """Test that nullable fields are correctly identified."""
        entities, _ = parse_models_directory(sample_models_dir)

        product_fields = {f.name: f for f in entities["Product"].fields}
        assert product_fields["description"].is_nullable is True
        assert product_fields["name"].is_nullable is False

    def test_parse_indexed_fields(self, sample_models_dir: Path):
        """Test that indexed fields are correctly identified."""
        entities, _ = parse_models_directory(sample_models_dir)

        user_fields = {f.name: f for f in entities["User"].fields}
        assert user_fields["email"].index is True
        assert user_fields["name"].index is False

    def test_parse_relationships(self, sample_models_dir: Path):
        """Test that relationships are correctly parsed."""
        entities, _ = parse_models_directory(sample_models_dir)

        user_rels = {r[2]: r for r in entities["User"].relationships}
        assert "orders" in user_rels
        assert user_rels["orders"][0] == "Order"
        assert user_rels["orders"][1] == "many"

    def test_parse_empty_models(self, empty_models_dir: Path):
        """Test parsing an empty models file."""
        entities, enums = parse_models_directory(empty_models_dir)

        assert len(entities) == 0
        assert len(enums) == 0

    def test_parse_inheritance(self, models_with_inheritance_dir: Path):
        """Test parsing models with inheritance."""
        entities, _ = parse_models_directory(models_with_inheritance_dir)

        assert "Article" in entities
        article_fields = {f.name: f for f in entities["Article"].fields}

        # Own fields
        assert "title" in article_fields
        assert "content" in article_fields

        # Inherited fields from BaseEntity and TimestampMixin
        assert "id" in article_fields
        assert "created_at" in article_fields
        assert "updated_at" in article_fields
