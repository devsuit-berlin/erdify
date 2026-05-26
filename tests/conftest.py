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
