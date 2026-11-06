"""Reading annotated class bodies: SQLModel, SQLAlchemy, Pydantic and dataclasses.

These frameworks declare members as annotated attributes (``x: int = ...``).
They share how a column, a ``Relationship()`` / ``relationship()`` and a
plain model reference are read; the concrete dialects only differ in detection
and in which of these member kinds they accept.
"""

import ast
from typing import Dict, List, Tuple

from ...config import FieldInfo
from ..annotations import (
    annotation_reference,
    as_rel,
    column_metadata,
    column_type,
    expand_aliases,
    is_call_to,
)
from ..common import _Rel
from .base import Dialect


class AnnotatedDialect(Dialect):
    """Base for dialects whose members are annotated attributes.

    A member assigned ``Relationship()`` / ``relationship()`` is a relationship
    in every one of them; ``keyless`` dialects (Pydantic / dataclass) also
    treat a field typed as another model as a relationship.
    """

    def class_fields(
        self, class_node: ast.ClassDef, concrete: str
    ) -> Tuple[Dict[str, FieldInfo], Dict[str, _Rel]]:
        """Extract fields and relationships from an annotated class body."""
        fields: Dict[str, FieldInfo] = {}
        relationships: Dict[str, _Rel] = {}

        for node in class_node.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                field_name = node.target.id
                if self.reads_annotated_columns:
                    node = self._with_aliases_expanded(node, class_node)

                # Skip special attributes
                if field_name.startswith("_"):
                    continue

                # Check for an explicit relationship call (SQLModel/SQLAlchemy)
                # SQLModel Relationship() / SQLAlchemy relationship(), also
                # module-qualified (orm.relationship, sqlmodel.Relationship).
                is_relationship = node.value is not None and (
                    is_call_to(node.value, "Relationship") or is_call_to(node.value, "relationship")
                )

                if is_relationship:
                    rel = self._parse_relationship(node)
                    if rel:
                        relationships[field_name] = rel
                    continue

                # Keyless sources (Pydantic/dataclass): a field typed as another
                # model is treated as a relationship rather than a column.
                if self.keyless:
                    rel = self._parse_model_reference(node)
                    if rel:
                        relationships[field_name] = rel
                        continue

                field = self._parse_field(node)
                if field:
                    fields[field_name] = field

        return fields, relationships

    @staticmethod
    def _declares_default(value: ast.expr | None) -> bool:
        """Whether the assigned value sets a default, even one that cannot be shown."""
        if value is None:
            return False
        if not is_call_to(value, "mapped_column"):
            return True  # `x: Mapped[str] = "a"` (MappedAsDataclass)
        return any(
            kw.arg in ("default", "default_factory", "insert_default") for kw in value.keywords
        )

    def _with_aliases_expanded(
        self, node: ast.AnnAssign, class_node: ast.ClassDef
    ) -> ast.AnnAssign:
        """``node`` with column type aliases expanded, as seen where its class is defined."""
        annotation = expand_aliases(node.annotation, self.ctx.aliases_for(class_node))
        if annotation is node.annotation:
            return node
        expanded = ast.AnnAssign(
            target=node.target, annotation=annotation, value=node.value, simple=node.simple
        )
        return ast.copy_location(expanded, node)

    def _parse_field(self, node: ast.AnnAssign) -> FieldInfo | None:
        """Parse a field from an annotated assignment."""
        if not isinstance(node.target, ast.Name):
            return None

        field_name = node.target.id
        type_str, is_nullable = column_type(node.annotation)

        # As in SQLAlchemy, the first mapped_column() in the Annotated metadata
        # (#241) is merged with the assigned Field() (SQLModel) / mapped_column()
        # (SQLAlchemy), bare or qualified (e.g. orm.mapped_column): what the
        # assigned call sets wins, except that primary_key=True from either
        # sticks. SQLModel ignores Field() keys in Annotated metadata.
        metadata_calls = (
            [
                call
                for call in column_metadata(node.annotation)
                if is_call_to(call, "mapped_column")
            ][:1]
            if self.reads_annotated_columns
            else []
        )
        calls: List[ast.Call] = list(metadata_calls)
        if node.value is not None and (
            is_call_to(node.value, "Field") or is_call_to(node.value, "mapped_column")
        ):
            calls.append(node.value)

        is_primary_key = False
        is_foreign_key = False
        foreign_table = None
        index = False
        is_unique = False
        for call in calls:
            for keyword in call.keywords:
                if isinstance(keyword.value, ast.Constant) and keyword.value.value is None:
                    continue  # `index=None` etc. means "unspecified" in SQLAlchemy
                if keyword.arg == "primary_key" and isinstance(keyword.value, ast.Constant):
                    is_primary_key = is_primary_key or bool(keyword.value.value)
                elif keyword.arg == "foreign_key" and isinstance(keyword.value, ast.Constant):
                    is_foreign_key = True
                    foreign_table = str(keyword.value.value)
                elif keyword.arg == "index" and isinstance(keyword.value, ast.Constant):
                    index = bool(keyword.value.value)
                elif keyword.arg == "unique" and isinstance(keyword.value, ast.Constant):
                    is_unique = bool(keyword.value.value)
                elif (
                    keyword.arg == "nullable"
                    and isinstance(keyword.value, ast.Constant)
                    and isinstance(keyword.value.value, bool)
                ):
                    # An explicit nullable=True/False is what the database gets
                    # and overrides the annotation; nullable=None means
                    # "unspecified", so the annotation still decides.
                    is_nullable = keyword.value.value

            # SQLAlchemy: ForeignKey("table.col") passed to mapped_column()
            fk_target = extract_foreign_key_arg(call)
            if fk_target is not None:
                is_foreign_key = True
                foreign_table = fk_target

        # Optional name-based key inference for keyless sources (Pydantic/dataclass).
        # Never overrides explicitly declared keys above.
        if self.ctx.infer_keys and self.keyless:
            if field_name == "id":
                is_primary_key = True
            elif field_name.endswith("_id"):
                is_foreign_key = True
                foreign_table = f"{field_name[: -len('_id')]}.id"

        # Extract default value
        default_value = self._extract_default_value(node)
        for call in metadata_calls:  # only when nothing assigned declares a default
            if self._declares_default(node.value):
                break
            default_value = self._extract_default_value(
                ast.AnnAssign(target=node.target, annotation=node.annotation, value=call, simple=1)
            )

        # A primary key is never NULL in the database. SQLModel's idiomatic
        # `id: int | None = Field(default=None, primary_key=True)` only means
        # "unset until the database assigns it", so drop the Optional and the
        # `None` default rather than render the key as nullable (#217). Keyless
        # sources (Pydantic/dataclass) describe objects, not tables: an inferred
        # `id: int | None = None` there really is optional, so keep it.
        if is_primary_key and not self.keyless:
            is_nullable = False
            if default_value == "None":
                default_value = None

        return FieldInfo(
            name=field_name,
            type_str=type_str,
            is_primary_key=is_primary_key,
            is_foreign_key=is_foreign_key,
            is_nullable=is_nullable,
            foreign_table=foreign_table,
            index=index,
            default_value=default_value,
            # is_unique is reserved for non-PK uniqueness (see FieldInfo).
            is_unique=is_unique and not is_primary_key,
        )

    def _extract_default_value(self, node: ast.AnnAssign) -> str | None:
        """Extract default value from field definition."""
        if not node.value:
            return None

        # Direct constant value (e.g., field: str = "value")
        if isinstance(node.value, ast.Constant):
            return repr(node.value.value)

        # Field() / mapped_column() with default parameter
        if isinstance(node.value, ast.Call):
            is_field = is_call_to(node.value, "Field")
            if is_field or is_call_to(node.value, "mapped_column"):
                # Positional default: only SQLModel's Field(default, ...).
                # mapped_column()'s positional args are the column name, type
                # and ForeignKey, never a default (#221).
                if node.value.args and is_field:
                    first_arg = node.value.args[0]
                    if isinstance(first_arg, ast.Constant):
                        return repr(first_arg.value)
                    elif isinstance(first_arg, ast.Attribute):
                        # Enum value like OrderStatus.PENDING
                        return (
                            f"{first_arg.value.id}.{first_arg.attr}"
                            if isinstance(first_arg.value, ast.Name)
                            else None
                        )

                # Check keyword args (Field(default=value))
                for keyword in node.value.keywords:
                    if keyword.arg == "default":
                        if isinstance(keyword.value, ast.Constant):
                            return repr(keyword.value.value)
                        elif isinstance(keyword.value, ast.Attribute):
                            # Enum value like OrderStatus.PENDING
                            if isinstance(keyword.value.value, ast.Name):
                                return f"{keyword.value.value.id}.{keyword.value.attr}"

        return None

    def _parse_relationship(self, node: ast.AnnAssign) -> _Rel | None:
        """Parse a relationship from an annotated assignment.

        A relationship that declares ``link_model=`` (SQLModel) or ``secondary=``
        (SQLAlchemy) is a many-to-many association already expressed by the link
        table. It must not be emitted as a direct edge - that would duplicate the
        link-table path and misrepresent the cardinality as 1:N - so it is skipped.
        """
        if not isinstance(node.target, ast.Name):
            return None

        if isinstance(node.value, ast.Call) and any(
            kw.arg in ("link_model", "secondary") for kw in node.value.keywords
        ):
            return None

        ref = annotation_reference(node.annotation)
        if ref is None:  # names no single class (e.g. Mapped[A | B]): nothing to draw
            return None
        rel = as_rel(ref, node.target.id)
        # back_populates= names the other side's attribute, so the two sides
        # can be paired exactly (#240). backref= creates that side implicitly,
        # so there is no second declaration to pair with.
        if isinstance(node.value, ast.Call):
            inverse = self._back_populates(node.value)
            if inverse is not None:
                rel = rel._replace(inverse=inverse)
        return rel

    @staticmethod
    def _back_populates(call: ast.Call) -> str | None:
        """``back_populates="x"``, also SQLModel's ``sa_relationship_kwargs={...}`` form."""
        for kw in call.keywords:
            value = kw.value
            if kw.arg == "back_populates":
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    return value.value
            elif kw.arg == "sa_relationship_kwargs" and isinstance(value, ast.Dict):
                for key, item in zip(value.keys, value.values):
                    if (
                        isinstance(key, ast.Constant)
                        and key.value == "back_populates"
                        and isinstance(item, ast.Constant)
                        and isinstance(item.value, str)
                    ):
                        return item.value
        return None

    def _parse_model_reference(self, node: ast.AnnAssign) -> _Rel | None:
        """Treat a field typed as another known model as a relationship.

        Used for Pydantic/dataclass models, which express relationships as plain
        typed attributes (e.g. ``user: User`` or ``items: list[Item]``) rather
        than via a Relationship()/relationship() call.
        """
        if not isinstance(node.target, ast.Name):
            return None

        ref = annotation_reference(node.annotation)
        # A qualified name (`other_service.User`) may be an external class that
        # merely shares a model's name; only an explicit relationship() trusts it.
        if ref is None or ref.qualified:
            return None
        target_class = self.classes.all.get(ref.target)
        if target_class is not None and self.ctx.classify(target_class) is not None:
            return as_rel(ref, node.target.id)
        return None


def extract_foreign_key_arg(call: ast.Call) -> str | None:
    """Extract the target from a ForeignKey("table.col") call argument.

    SQLAlchemy expresses foreign keys as `mapped_column(ForeignKey("user.id"))`,
    where ForeignKey may appear as a positional or keyword argument.
    """
    candidates = list(call.args) + [kw.value for kw in call.keywords]
    for arg in candidates:
        if (
            is_call_to(arg, "ForeignKey")  # also sa.ForeignKey
            and arg.args
            and isinstance(arg.args[0], ast.Constant)
        ):
            return str(arg.args[0].value)
    return None
