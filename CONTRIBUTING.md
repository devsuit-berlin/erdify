# 🤝 Contributing to erdify

First off, thank you for considering contributing to erdify! 🎉

## 📋 Table of Contents

- [Code of Conduct](#-code-of-conduct)
- [Getting Started](#-getting-started)
- [Development Setup](#️-development-setup)
- [Making Changes](#️-making-changes)
- [Testing](#-testing)
- [Submitting Changes](#-submitting-changes)
- [Style Guide](#-style-guide)

## 📜 Code of Conduct

This project and everyone participating in it is governed by our commitment to providing a welcoming and inclusive environment. Please be respectful and constructive in all interactions.

## 🚀 Getting Started

### Prerequisites

- Python 3.10 or higher
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- Git

### Finding Something to Work On

- 🐛 **Bug fixes**: Check the [issues](https://github.com/devsuit-berlin/erdify/issues) labeled `bug`
- ✨ **Features**: Look for issues labeled `enhancement`
- 📖 **Documentation**: Help improve our docs
- 🧪 **Tests**: Increase test coverage

## 🛠️ Development Setup

### 1. Fork and Clone

```bash
# Fork the repository on GitHub, then:
git clone https://github.com/YOUR_USERNAME/erdify.git
cd erdify
```

### 2. Set Up Environment

Using uv (recommended):

```bash
# Install uv if you haven't
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create virtual environment and install dependencies
uv sync
```

Using pip:

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

### 3. Verify Setup

```bash
# Run tests
uv run pytest

# Run type checking
uv run mypy src/

# Run linting
uv run ruff check src/ tests/
```

## ✏️ Making Changes

### 1. Create a Branch

```bash
git checkout -b feature/your-feature-name
# or
git checkout -b fix/your-bug-fix
```

### 2. Project Structure

```bash
erdify/
├── src/erdify/
│   ├── __init__.py      # Public API exports
│   ├── __main__.py      # python -m entry point
│   ├── cli.py           # Command-line interface
│   ├── config.py        # Data classes (FieldInfo, EntityInfo, etc.)
│   ├── generator.py     # PlantUML generation
│   └── parser.py        # AST parsing logic
├── tests/
│   ├── fixtures/        # Test model files
│   │   ├── ecommerce/   # E-commerce example models
│   │   ├── edge_cases/  # Edge case models
│   │   ├── empty/       # Empty models (no tables)
│   │   ├── inheritance/ # Inheritance example models
│   │   └── malformed/   # Malformed Python (error handling tests)
│   ├── conftest.py      # Pytest fixtures
│   ├── test_cli.py
│   ├── test_config.py
│   ├── test_edge_cases.py
│   ├── test_generator.py
│   ├── test_integration.py
│   └── test_parser.py
└── pyproject.toml
```

### 3. Make Your Changes

- Keep changes focused and atomic
- Follow the existing code style
- Add/update tests for your changes
- Update documentation if needed

## 🧪 Testing

### Running Tests

```bash
# Run all tests
uv run pytest

# Run with verbose output
uv run pytest -v

# Run specific test file
uv run pytest tests/test_parser.py

# Run with coverage
uv run pytest --cov=erdify --cov-report=html
```

### Writing Tests

- Place tests in the appropriate `test_*.py` file
- Use descriptive test names: `test_parse_foreign_key_with_custom_table`
- Use fixtures from `conftest.py` when possible

### Golden File Tests

For integration tests, we use golden files (expected output files):

```bash
# If you intentionally change the output format, update golden files:
erdify tests/fixtures/ecommerce --title 'E-Commerce ERD' -o tests/fixtures/ecommerce/expected.puml
```

### Adding New Test Fixtures

1. Create a new directory under `tests/fixtures/`
2. Add a `models.py` with your SQLModel definitions
3. Generate the expected output:

   ```bash
   erdify tests/fixtures/your_fixture -o tests/fixtures/your_fixture/expected.puml
   ```

4. Add the fixture to `test_integration.py`

## 📤 Submitting Changes

### 1. Ensure Quality

```bash
# Format code
uv run ruff format src/ tests/

# Check linting
uv run ruff check src/ tests/

# Run type checking
uv run mypy src/

# Run all tests
uv run pytest
```

### 2. Commit Your Changes

We follow [Conventional Commits](https://www.conventionalcommits.org/):

```bash
git add .
git commit -m "feat: add support for composite primary keys"
# or
git commit -m "fix: handle nullable foreign keys correctly"
# or
git commit -m "docs: improve CLI usage examples"
```

**Commit Types:**

- `feature`: New feature
- `bugfix`: Bug fix
- `docs`: Documentation changes
- `test`: Adding/updating tests
- `refactor`: Code refactoring
- `style`: Formatting changes
- `chore`: Maintenance tasks

### 3. Push and Create PR

```bash
git push origin feature/your-feature-name
```

Then open a Pull Request on GitHub with:

- Clear title describing the change
- Description of what and why
- Link to related issues (e.g., "Fixes #123")

## 📝 Style Guide

### Python Code

- Follow [PEP 8](https://pep8.org/)
- Use type hints for all public functions
- Maximum line length: 100 characters
- Use `ruff` for formatting and linting

### Documentation

- Use docstrings for all public modules, classes, and functions
- Follow [Google style docstrings](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings)
- Keep README and other docs up to date

### Example Docstring

```python
def parse_models_directory(
    path: Path, exclude_patterns: list[str] | None = None
) -> tuple[dict[str, EntityInfo], dict[str, EnumInfo]]:
    """
    Parse all SQLModel models in a directory.

    Args:
        path: Path to directory containing model files.
        exclude_patterns: List of glob patterns to exclude.

    Returns:
        Tuple of (entities dict, enums dict).

    Raises:
        FileNotFoundError: If path does not exist.

    Example:
        >>> entities, enums = parse_models_directory(Path("./models"))
        >>> print(len(entities))
        5
    """
```

## 💡 Tips

- **Small PRs are better**: They're easier to review and merge
- **Ask questions**: Open an issue if you're unsure about something
- **Test edge cases**: Think about what could go wrong
- **Update docs**: If you add a feature, document it

## 🎉 Thank You!

Every contribution helps make erdify better. We appreciate your time and effort! 💪
