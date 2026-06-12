"""Tests for parsing Pydantic (BaseModel) models."""

from pathlib import Path

from erdify.parser import parse_models_directory


class TestPydanticParsing:
    """Tests for Pydantic model parsing (no --infer-keys)."""

    def test_parse_entities(self, pydantic_models_dir: Path):
        """Every BaseModel subclass becomes an entity."""
        entities, _ = parse_models_directory(pydantic_models_dir)

        assert "Customer" in entities
        assert "Invoice" in entities
        assert "Identifiable" in entities  # direct BaseModel subclass

    def test_entities_have_pydantic_source(self, pydantic_models_dir: Path):
        """Parsed Pydantic models are tagged with source 'pydantic'."""
        entities, _ = parse_models_directory(pydantic_models_dir)
        assert entities["Customer"].source == "pydantic"

    def test_indirect_basemodel_subclass_detected(self, pydantic_models_dir: Path):
        """A class inheriting BaseModel transitively is still detected."""
        entities, _ = parse_models_directory(pydantic_models_dir)
        # Customer(Identifiable) where Identifiable(BaseModel)
        assert "Customer" in entities

    def test_table_name_snake_case_fallback(self, pydantic_models_dir: Path):
        """Without __tablename__, the table name is the snake_case class name."""
        entities, _ = parse_models_directory(pydantic_models_dir)
        assert entities["Customer"].table_name == "customer"
        assert entities["Invoice"].table_name == "invoice"

    def test_inherited_fields(self, pydantic_models_dir: Path):
        """Fields from a base model are inherited."""
        entities, _ = parse_models_directory(pydantic_models_dir)
        customer_fields = {f.name for f in entities["Customer"].fields}
        assert "id" in customer_fields  # from Identifiable
        assert "name" in customer_fields

    def test_nested_ref_is_relationship_many(self, pydantic_models_dir: Path):
        """A list of another model is a 'many' relationship, not a column."""
        entities, _ = parse_models_directory(pydantic_models_dir)
        customer_rels = {r[2]: r for r in entities["Customer"].relationships}
        assert "invoices" in customer_rels
        assert customer_rels["invoices"][0] == "Invoice"
        assert customer_rels["invoices"][1] == "many"

        customer_field_names = {f.name for f in entities["Customer"].fields}
        assert "invoices" not in customer_field_names

    def test_nested_ref_is_relationship_one(self, pydantic_models_dir: Path):
        """A single model reference is a 'one' relationship."""
        entities, _ = parse_models_directory(pydantic_models_dir)
        invoice_rels = {r[2]: r for r in entities["Invoice"].relationships}
        assert "customer" in invoice_rels
        assert invoice_rels["customer"][0] == "Customer"
        assert invoice_rels["customer"][1] == "one"

    def test_no_keys_inferred_by_default(self, pydantic_models_dir: Path):
        """Without --infer-keys, id/<x>_id are plain columns."""
        entities, _ = parse_models_directory(pydantic_models_dir)
        invoice_fields = {f.name: f for f in entities["Invoice"].fields}
        assert invoice_fields["id"].is_primary_key is False
        assert invoice_fields["customer_id"].is_foreign_key is False

    def test_nullable_optional(self, pydantic_models_dir: Path):
        """Optional[...] fields are nullable."""
        entities, _ = parse_models_directory(pydantic_models_dir)
        customer_fields = {f.name: f for f in entities["Customer"].fields}
        assert customer_fields["email"].is_nullable is True
        assert customer_fields["name"].is_nullable is False

    def test_enum_detected(self, pydantic_models_dir: Path):
        """Enums are detected alongside Pydantic models."""
        _, enums = parse_models_directory(pydantic_models_dir)
        assert "Priority" in enums
        assert "LOW" in enums["Priority"].values
