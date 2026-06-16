"""Pytest fixtures for erdify tests."""

import shutil
import tempfile
from pathlib import Path

import pytest

# Path to static fixtures
FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    temp_path = Path(tempfile.mkdtemp())
    yield temp_path
    shutil.rmtree(temp_path)


@pytest.fixture
def sample_models_dir() -> Path:
    """Path to sample e-commerce models directory."""
    return FIXTURES_DIR / "ecommerce"


@pytest.fixture
def empty_models_dir() -> Path:
    """Path to empty models directory."""
    return FIXTURES_DIR / "empty"


@pytest.fixture
def models_with_inheritance_dir() -> Path:
    """Path to models with inheritance."""
    return FIXTURES_DIR / "inheritance"


@pytest.fixture
def edge_cases_dir() -> Path:
    """Path to edge case models."""
    return FIXTURES_DIR / "edge_cases"


@pytest.fixture
def malformed_models_dir() -> Path:
    """Path to malformed Python models (syntax errors)."""
    return FIXTURES_DIR / "malformed"


@pytest.fixture
def sqlalchemy_models_dir() -> Path:
    """Path to SQLAlchemy 2.0 (Mapped/mapped_column) models directory."""
    return FIXTURES_DIR / "sqlalchemy"


@pytest.fixture
def pydantic_models_dir() -> Path:
    """Path to Pydantic models directory."""
    return FIXTURES_DIR / "pydantic"


@pytest.fixture
def dataclass_models_dir() -> Path:
    """Path to dataclass models directory."""
    return FIXTURES_DIR / "dataclasses"


@pytest.fixture
def m2m_link_model_dir() -> Path:
    """Path to SQLModel many-to-many (Relationship link_model=) models."""
    return FIXTURES_DIR / "m2m_link_model"


@pytest.fixture
def m2m_secondary_dir() -> Path:
    """Path to SQLAlchemy many-to-many (relationship secondary=) models."""
    return FIXTURES_DIR / "m2m_secondary"


@pytest.fixture
def link_detection_dir() -> Path:
    """Path to structural link-table detection models (#35)."""
    return FIXTURES_DIR / "link_detection"


@pytest.fixture
def m2m_secondary_table_dir() -> Path:
    """Path to SQLAlchemy M:N via relationship(secondary=Table(...)) (#34)."""
    return FIXTURES_DIR / "m2m_secondary_table"


@pytest.fixture
def django_models_dir() -> Path:
    """Path to Django ORM models directory (#36)."""
    return FIXTURES_DIR / "django"
