"""Sample SQLModel models for testing edge cases."""

import enum

from sqlmodel import Field, SQLModel


# Enum using enum.Enum (qualified import)
class PaymentMethod(enum.Enum):
    """Payment method using qualified enum.Enum."""

    CREDIT_CARD = "credit_card"
    PAYPAL = "paypal"
    BANK_TRANSFER = "bank_transfer"


class EmptyEntity(SQLModel, table=True):
    """Entity with no fields (edge case)."""

    __tablename__: str = "empty_entity"

    id: int = Field(primary_key=True)


class EntityWithPositionalDefault(SQLModel, table=True):
    """Entity with positional default in Field()."""

    __tablename__: str = "entity_with_positional"

    id: int = Field(primary_key=True)
    status: str = Field("pending")  # Positional default
    payment: PaymentMethod = Field(PaymentMethod.CREDIT_CARD)  # Positional enum default


class LinkTableWithThreeKeys(SQLModel, table=True):
    """Invalid link table with 3 FKs (edge case)."""

    __tablename__: str = "three_key_link"

    entity_a_id: int = Field(foreign_key="entity_a.id", primary_key=True)
    entity_b_id: int = Field(foreign_key="entity_b.id", primary_key=True)
    entity_c_id: int = Field(foreign_key="entity_c.id", primary_key=True)


class EntityWithNoTableName(SQLModel, table=True):
    """Entity without explicit __tablename__ (uses class name conversion)."""

    id: int = Field(primary_key=True)
    name: str
