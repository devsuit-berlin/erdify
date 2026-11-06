"""The parser's dialect layer (#81): registry, classification and shared hooks."""

import ast
from pathlib import Path

from erdify.parser import MODEL_SOURCES, ASTDatabaseParser, parse_models_directory
from erdify.parser.dialects import DIALECTS, ParseContext
from erdify.parser.dialects.keyless import PydanticDialect
from erdify.parser.inheritance import ClassIndex


def test_model_sources_follow_dialect_order():
    """--sources choices and classification order come from one registry."""
    assert MODEL_SOURCES == ("sqlmodel", "sqlalchemy", "django", "dataclass", "pydantic")
    assert [d.kind for d in DIALECTS] == list(MODEL_SOURCES)


def test_classify_before_parsing(tmp_path: Path):
    """Classification works on a fresh parser, before parse_all_models() ran."""
    node = ast.parse("class A(SQLModel, table=True):\n    id: int\n").body[0]
    assert isinstance(node, ast.ClassDef)
    assert ASTDatabaseParser(tmp_path)._classify_source(node) == "sqlmodel"


def test_default_context_resolves_model_references():
    """A dialect on a default context still classifies referenced models."""
    tree = ast.parse(
        "class User(BaseModel):\n    id: int\n\n\nclass Post(BaseModel):\n    user: User\n"
    )
    classes = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
    dialect = PydanticDialect(ParseContext(classes=ClassIndex(classes)))
    fields, rels = dialect.class_fields(classes["Post"], "Post")
    assert fields == {}
    assert rels == {"user": ("User", "one", "user", False)}


def test_django_table_args_uniqueness_kept(tmp_path: Path):
    """The __table_args__ uniqueness pass runs for every dialect, as before #81."""
    (tmp_path / "models.py").write_text(
        "from django.db import models\n"
        "from sqlalchemy import UniqueConstraint\n\n\n"
        "class Account(models.Model):\n"
        '    __table_args__ = (UniqueConstraint("email"),)\n'
        "    email = models.CharField(max_length=50)\n",
        encoding="utf-8",
    )
    entities, _ = parse_models_directory(tmp_path)
    assert [(f.name, f.is_unique) for f in entities["Account"].fields] == [
        ("id", False),
        ("email", True),
    ]
