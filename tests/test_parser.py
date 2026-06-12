"""Tests for cross-cutting parser behavior (exclude patterns, convenience API).

Model-type-specific parsing tests live in their own files:
test_sqlmodel.py, test_sqlalchemy.py, test_pydantic.py, test_dataclass.py.
"""

from pathlib import Path

from erdify.parser import parse_models_directory


class TestExcludePatterns:
    """Tests for the --exclude pattern filtering."""

    def test_exclude_by_class_name_glob(self, sample_models_dir: Path):
        """Entities whose class name matches a glob are removed."""
        entities, _ = parse_models_directory(sample_models_dir, exclude_patterns=["*Link"])

        assert "UserProductLink" not in entities
        assert "User" in entities

    def test_exclude_by_table_name_glob(self, sample_models_dir: Path):
        """Entities whose table name matches a glob are removed."""
        entities, _ = parse_models_directory(sample_models_dir, exclude_patterns=["order_item"])

        assert "OrderItem" not in entities
        assert "Order" in entities

    def test_exclude_is_case_sensitive_glob(self, sample_models_dir: Path):
        """Patterns are case-sensitive; a lowercase pattern matches the table name."""
        entities, _ = parse_models_directory(sample_models_dir, exclude_patterns=["user"])

        # class name is "User" (capital U) so a lowercase exact pattern must not match it,
        # but it DOES match the table name "user".
        assert "User" not in entities  # matched via table_name "user"

    def test_exclude_multiple_patterns(self, sample_models_dir: Path):
        """Multiple patterns are OR-ed together."""
        entities, _ = parse_models_directory(
            sample_models_dir, exclude_patterns=["Product", "*Link"]
        )

        assert "Product" not in entities
        assert "UserProductLink" not in entities
        assert "User" in entities

    def test_exclude_empty_patterns_keeps_all(self, sample_models_dir: Path):
        """An empty/None pattern list excludes nothing."""
        entities, _ = parse_models_directory(sample_models_dir, exclude_patterns=[])
        all_entities, _ = parse_models_directory(sample_models_dir)
        assert set(entities) == set(all_entities)

    def test_exclude_strips_dangling_relationships(self, sample_models_dir: Path):
        """Relationships pointing at an excluded entity are dropped."""
        entities, _ = parse_models_directory(sample_models_dir, exclude_patterns=["Order"])

        # User.orders relationship targets the now-excluded Order entity.
        user_rel_targets = {r[0] for r in entities["User"].relationships}
        assert "Order" not in user_rel_targets


class TestInferKeys:
    """Tests for the --infer-keys name-based PK/FK heuristic."""

    def test_infer_pk_from_id(self, pydantic_models_dir: Path):
        """With infer_keys, a field named 'id' becomes a primary key."""
        entities, _ = parse_models_directory(pydantic_models_dir, infer_keys=True)
        invoice_fields = {f.name: f for f in entities["Invoice"].fields}
        assert invoice_fields["id"].is_primary_key is True

    def test_infer_fk_from_suffix(self, pydantic_models_dir: Path):
        """With infer_keys, '<x>_id' becomes a foreign key to table '<x>'."""
        entities, _ = parse_models_directory(pydantic_models_dir, infer_keys=True)
        invoice_fields = {f.name: f for f in entities["Invoice"].fields}
        assert invoice_fields["customer_id"].is_foreign_key is True
        assert invoice_fields["customer_id"].foreign_table == "customer.id"

    def test_infer_keys_works_for_dataclass(self, dataclass_models_dir: Path):
        """Inference also applies to dataclasses."""
        entities, _ = parse_models_directory(dataclass_models_dir, infer_keys=True)
        item_fields = {f.name: f for f in entities["Item"].fields}
        assert item_fields["id"].is_primary_key is True
        assert item_fields["warehouse_id"].is_foreign_key is True
        assert item_fields["warehouse_id"].foreign_table == "warehouse.id"

    def test_infer_keys_does_not_touch_sqlmodel(self, sample_models_dir: Path):
        """Inference is scoped to keyless sources; SQLModel keys are unchanged."""
        entities, _ = parse_models_directory(sample_models_dir, infer_keys=True)
        # 'total' in Order is a plain float column, must not become a key.
        order_fields = {f.name: f for f in entities["Order"].fields}
        assert order_fields["total"].is_primary_key is False
        assert order_fields["total"].is_foreign_key is False
        # Explicit FK stays intact.
        assert order_fields["user_id"].is_foreign_key is True


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
