"""A field's alias is for (de)serialisation; the field keeps its attribute name."""

from pydantic import BaseModel, Field


class Customer(BaseModel):
    customer_id: int = Field(alias="customerId")
    full_name: str = Field(validation_alias="name", serialization_alias="fullName")
