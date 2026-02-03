"""Malformed Python file for testing error handling."""

# This file contains invalid Python syntax
class BrokenModel(SQLModel:  # Missing comma and closing parenthesis
    id: int = Field(primary_key=True)
