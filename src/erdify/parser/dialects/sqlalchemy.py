"""SQLModel and SQLAlchemy 2.0 (ORM classes and Core association tables)."""

import ast
from typing import Iterable, List

from ...config import EntityInfo, FieldInfo, is_structural_link_table
from ..annotations import is_call_to, is_mapped_annotation
from .annotated import AnnotatedDialect, extract_foreign_key_arg


class SQLModelDialect(AnnotatedDialect):
    """SQLModel: a class declared with ``table=True``."""

    kind = "sqlmodel"

    def detect(self, class_node: ast.ClassDef) -> bool:
        for keyword in class_node.keywords:
            if keyword.arg == "table" and isinstance(keyword.value, ast.Constant):
                if keyword.value.value:
                    return True
        return False


class SQLAlchemyDialect(AnnotatedDialect):
    """SQLAlchemy 2.0: a concrete mapped class has ``__tablename__`` and ``Mapped[...]``.

    Mixins / abstract bases (``Mapped`` fields but no ``__tablename__``) are not
    detected, so they are not emitted as entities, but their fields are still
    inherited.
    """

    kind = "sqlalchemy"

    def detect(self, class_node: ast.ClassDef) -> bool:
        return has_tablename(class_node) and has_mapped_field(class_node)

    def extra_entities(self, trees: Iterable[ast.Module]) -> List[EntityInfo]:
        """Core association tables (:func:`core_association_tables`, #34)."""
        return core_association_tables(trees)


def core_association_tables(trees: Iterable[ast.Module]) -> List[EntityInfo]:
    """Link entities from module-level Core ``Table(...)`` assignments.

    ``relationship(secondary=Table(...))`` points at a SQLAlchemy Core table
    rather than a mapped class. Only class definitions become entities in the
    normal passes, so such association tables - and their M:N - would be lost.
    Parse module-level ``name = Table("t", metadata, Column(...), ...)``
    assignments that are structurally association tables (a composite PK
    made up entirely of FK columns) and return them as link entities (#34).
    """
    entities: List[EntityInfo] = []
    for tree in trees:
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                continue
            if not is_call_to(node.value, "Table"):
                continue

            entity = build_core_table_entity(node.targets[0].id, node.value)
            if entity is not None:
                entities.append(entity)
    return entities


def has_tablename(class_node: ast.ClassDef) -> bool:
    """Check if a class assigns __tablename__ (annotated or plain)."""
    for node in class_node.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "__tablename__":
                return True
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__tablename__":
                    return True
    return False


def has_mapped_field(class_node: ast.ClassDef) -> bool:
    """Check if a class has at least one Mapped[...] annotated field."""
    for node in class_node.body:
        if isinstance(node, ast.AnnAssign) and is_mapped_annotation(node.annotation):
            return True
    return False


def build_core_table_entity(var_name: str, call: ast.Call) -> EntityInfo | None:
    """Build a link EntityInfo from a Core ``Table(...)`` call, or None if it
    is not structurally an association table."""
    # Table name is the first positional string arg; fall back to variable name.
    table_name = var_name
    if call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
        table_name = call.args[0].value

    fields: List[FieldInfo] = []
    for arg in call.args:
        if is_call_to(arg, "Column"):
            field = parse_core_column(arg)
            if field is not None:
                fields.append(field)

    if not is_structural_link_table(fields):
        return None

    entity = EntityInfo(
        name=var_name,
        table_name=table_name,
        base_classes=[],
        source="sqlalchemy",
    )
    entity.fields = fields
    entity.is_link_table = True
    return entity


def parse_core_column(call: ast.Call) -> FieldInfo | None:
    """Parse a Core ``Column("name", <Type>, ForeignKey(...), primary_key=...)``."""
    if not call.args or not isinstance(call.args[0], ast.Constant):
        return None
    col_name = str(call.args[0].value)

    is_primary_key = False
    for keyword in call.keywords:
        if keyword.arg == "primary_key" and isinstance(keyword.value, ast.Constant):
            is_primary_key = bool(keyword.value.value)

    fk_target = extract_foreign_key_arg(call)

    # An optional positional column type (e.g. Column("id", Integer, ...)).
    type_str = ""
    for arg in call.args[1:]:
        if isinstance(arg, ast.Name):
            type_str = arg.id
            break
        if isinstance(arg, ast.Attribute):
            type_str = arg.attr
            break

    return FieldInfo(
        name=col_name,
        type_str=type_str,
        is_primary_key=is_primary_key,
        is_foreign_key=fk_target is not None,
        foreign_table=fk_target,
    )
