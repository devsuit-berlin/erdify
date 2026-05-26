"""Tests for config module (dataclasses)."""

from erdify.config import FieldInfo, EnumInfo, EntityInfo


class TestFieldInfo:
    """Tests for FieldInfo dataclass."""

    def test_basic_field(self):
        """Test creating a basic field."""
        field = FieldInfo(name="id", type_str="int")
        assert field.name == "id"
        assert field.type_str == "int"
        assert field.is_primary_key is False
        assert field.is_foreign_key is False
        assert field.is_nullable is False
        assert field.foreign_table is None
        assert field.index is False
        assert field.default_value is None

    def test_primary_key_field(self):
        """Test creating a primary key field."""
        field = FieldInfo(name="id", type_str="int", is_primary_key=True)
        assert field.is_primary_key is True

    def test_foreign_key_field(self):
        """Test creating a foreign key field."""
        field = FieldInfo(
            name="user_id",
            type_str="int",
            is_foreign_key=True,
            foreign_table="user.id",
        )
        assert field.is_foreign_key is True
        assert field.foreign_table == "user.id"

    def test_nullable_field(self):
        """Test creating a nullable field."""
        field = FieldInfo(name="description", type_str="str", is_nullable=True)
        assert field.is_nullable is True

    def test_field_with_default(self):
        """Test creating a field with default value."""
        field = FieldInfo(name="is_active", type_str="bool", default_value="True")
        assert field.default_value == "True"


class TestEnumInfo:
    """Tests for EnumInfo dataclass."""

    def test_basic_enum(self):
        """Test creating a basic enum."""
        enum = EnumInfo(name="UserRole", values=["ADMIN", "USER", "GUEST"])
        assert enum.name == "UserRole"
        assert enum.values == ["ADMIN", "USER", "GUEST"]

    def test_empty_enum(self):
        """Test creating an enum with no values."""
        enum = EnumInfo(name="EmptyEnum")
        assert enum.name == "EmptyEnum"
        assert enum.values == []


class TestEntityInfo:
    """Tests for EntityInfo dataclass."""

    def test_basic_entity(self):
        """Test creating a basic entity."""
        entity = EntityInfo(name="User", table_name="user")
        assert entity.name == "User"
        assert entity.table_name == "user"
        assert entity.fields == []
        assert entity.relationships == []
        assert entity.is_link_table is False
        assert entity.base_classes == []

    def test_entity_with_fields(self):
        """Test creating an entity with fields."""
        fields = [
            FieldInfo(name="id", type_str="int", is_primary_key=True),
            FieldInfo(name="name", type_str="str"),
        ]
        entity = EntityInfo(name="User", table_name="user", fields=fields)
        assert len(entity.fields) == 2
        assert entity.fields[0].name == "id"

    def test_link_table_entity(self):
        """Test creating a link table entity."""
        entity = EntityInfo(
            name="UserProductLink",
            table_name="user_product_link",
            is_link_table=True,
        )
        assert entity.is_link_table is True

    def test_entity_with_relationships(self):
        """Test creating an entity with relationships."""
        relationships = [("Order", "many", "orders")]
        entity = EntityInfo(
            name="User",
            table_name="user",
            relationships=relationships,
        )
        assert len(entity.relationships) == 1
        assert entity.relationships[0] == ("Order", "many", "orders")
