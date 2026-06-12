"""Tests for parsing standard library @dataclass models."""

from pathlib import Path

from erdify.parser import parse_models_directory


class TestDataclassParsing:
    """Tests for dataclass model parsing (no --infer-keys)."""

    def test_parse_entities(self, dataclass_models_dir: Path):
        """@dataclass-decorated classes become entities."""
        entities, _ = parse_models_directory(dataclass_models_dir)
        assert "Warehouse" in entities
        assert "Item" in entities

    def test_entities_have_dataclass_source(self, dataclass_models_dir: Path):
        """Parsed dataclasses are tagged with source 'dataclass'."""
        entities, _ = parse_models_directory(dataclass_models_dir)
        assert entities["Warehouse"].source == "dataclass"

    def test_table_name_snake_case_fallback(self, dataclass_models_dir: Path):
        """Without __tablename__, the table name is the snake_case class name."""
        entities, _ = parse_models_directory(dataclass_models_dir)
        assert entities["Warehouse"].table_name == "warehouse"

    def test_fields_parsed(self, dataclass_models_dir: Path):
        """Plain annotated fields are parsed as columns."""
        entities, _ = parse_models_directory(dataclass_models_dir)
        warehouse_fields = {f.name for f in entities["Warehouse"].fields}
        assert "id" in warehouse_fields
        assert "name" in warehouse_fields

    def test_nested_ref_is_relationship_many(self, dataclass_models_dir: Path):
        """A list of another model is a 'many' relationship, not a column."""
        entities, _ = parse_models_directory(dataclass_models_dir)
        warehouse_rels = {r[2]: r for r in entities["Warehouse"].relationships}
        assert "items" in warehouse_rels
        assert warehouse_rels["items"][0] == "Item"
        assert warehouse_rels["items"][1] == "many"

        warehouse_field_names = {f.name for f in entities["Warehouse"].fields}
        assert "items" not in warehouse_field_names

    def test_nested_ref_is_relationship_one(self, dataclass_models_dir: Path):
        """An Optional single model reference is a 'one' relationship."""
        entities, _ = parse_models_directory(dataclass_models_dir)
        item_rels = {r[2]: r for r in entities["Item"].relationships}
        assert "warehouse" in item_rels
        assert item_rels["warehouse"][0] == "Warehouse"
        assert item_rels["warehouse"][1] == "one"

    def test_no_keys_inferred_by_default(self, dataclass_models_dir: Path):
        """Without --infer-keys, id/<x>_id are plain columns."""
        entities, _ = parse_models_directory(dataclass_models_dir)
        item_fields = {f.name: f for f in entities["Item"].fields}
        assert item_fields["id"].is_primary_key is False
        assert item_fields["warehouse_id"].is_foreign_key is False

    def test_nullable_optional(self, dataclass_models_dir: Path):
        """Optional[...] and X | None fields are nullable."""
        entities, _ = parse_models_directory(dataclass_models_dir)
        warehouse_fields = {f.name: f for f in entities["Warehouse"].fields}
        item_fields = {f.name: f for f in entities["Item"].fields}
        assert warehouse_fields["location"].is_nullable is True
        assert item_fields["note"].is_nullable is True
