"""Reading annotated class bodies: SQLModel, SQLAlchemy, Pydantic and dataclasses.

These frameworks declare members as annotated attributes (``x: int = ...``).
They share how a column, a ``Relationship()`` / ``relationship()`` and a
plain model reference are read; the concrete dialects only differ in detection
and in which of these member kinds they accept.
"""

import ast
from typing import Dict, Tuple

from ...config import EntityInfo, FieldInfo
from ..annotations import annotation_reference, as_rel, column_type, is_call_to
from ..common import _Rel
from .base import Dialect


class AnnotatedDialect(Dialect):
    """Base for dialects whose members are annotated attributes.

    A member assigned ``Relationship()`` / ``relationship()`` is a relationship
    in every one of them; ``model_references`` dialects (Pydantic / dataclass)
    also treat a field typed as another model as a relationship.
    """

    #: A field typed as another model is a relationship rather than a column.
    model_references = False

    def class_fields(
        self, class_node: ast.ClassDef, concrete: str
    ) -> Tuple[Dict[str, FieldInfo], Dict[str, _Rel]]:
        """Extract fields and relationships from an annotated class body."""
        fields: Dict[str, FieldInfo] = {}
        relationships: Dict[str, _Rel] = {}

        for node in class_node.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                field_name = node.target.id

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
                if self.model_references:
                    rel = self._parse_model_reference(node)
                    if rel:
                        relationships[field_name] = rel
                        continue

                field = self._parse_field(node, self.kind)
                if field:
                    fields[field_name] = field

        return fields, relationships

    def finish(self, entity: EntityInfo, class_node: ast.ClassDef) -> None:
        """Mark columns made unique by ``__table_args__``."""
        # Single-column UniqueConstraint / unique Index in __table_args__ (#218).
        # Constraints name the *database* column, which mapped_column("col", ...)
        # may set apart from the attribute name (#221).
        # A string names the DB column; a bare reference names the attribute.
        unique_cols, unique_refs = self._table_args_unique_columns(class_node)
        db_names = self._db_column_names(class_node)
        for f in entity.fields:
            if f.is_primary_key:
                continue
            if db_names.get(f.name, f.name) in unique_cols or f.name in unique_refs:
                f.is_unique = True

    def _parse_field(self, node: ast.AnnAssign, model_kind: str) -> FieldInfo | None:
        """Parse a field from an annotated assignment."""
        if not isinstance(node.target, ast.Name):
            return None

        field_name = node.target.id
        type_str, is_nullable = column_type(node.annotation)

        # Parse Field() / mapped_column() parameters
        is_primary_key = False
        is_foreign_key = False
        foreign_table = None
        index = False
        is_unique = False

        if node.value and isinstance(node.value, ast.Call):
            # Field() (SQLModel) / mapped_column() (SQLAlchemy), bare or qualified
            # (e.g. orm.mapped_column).
            if is_call_to(node.value, "Field") or is_call_to(node.value, "mapped_column"):
                for keyword in node.value.keywords:
                    if keyword.arg == "primary_key" and isinstance(keyword.value, ast.Constant):
                        is_primary_key = bool(keyword.value.value)
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
                fk_target = extract_foreign_key_arg(node.value)
                if fk_target is not None:
                    is_foreign_key = True
                    foreign_table = fk_target

        # Optional name-based key inference for keyless sources (Pydantic/dataclass).
        # Never overrides explicitly declared keys above.
        if self.ctx.infer_keys and model_kind in ("pydantic", "dataclass"):
            if field_name == "id":
                is_primary_key = True
            elif field_name.endswith("_id"):
                is_foreign_key = True
                foreign_table = f"{field_name[: -len('_id')]}.id"

        # Extract default value
        default_value = self._extract_default_value(node)

        # A primary key is never NULL in the database. SQLModel's idiomatic
        # `id: int | None = Field(default=None, primary_key=True)` only means
        # "unset until the database assigns it", so drop the Optional and the
        # `None` default rather than render the key as nullable (#217). Keyless
        # sources (Pydantic/dataclass) describe objects, not tables: an inferred
        # `id: int | None = None` there really is optional, so keep it.
        if is_primary_key and model_kind in ("sqlmodel", "sqlalchemy"):
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
        return as_rel(ref, node.target.id)

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

    def _db_column_names(self, class_node: ast.ClassDef) -> Dict[str, str]:
        """Map attribute name -> explicit DB column name for a class and its bases.

        See :meth:`_explicit_column_name` for the recognized forms. A column
        without an explicit name maps to itself, so a redeclaration without one
        overrides an inherited name. Bases resolve in the same order as the
        fields (:meth:`ClassIndex.merge_order`), so the name matches the winning column.
        """
        names: Dict[str, str] = {}
        for class_name in self.classes.merge_order(class_node):
            for node in self.classes.all[class_name].body:
                if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    db_name = self._explicit_column_name(node.value)
                    names[node.target.id] = db_name if db_name is not None else node.target.id
        return names

    @classmethod
    def _explicit_column_name(cls, value: ast.expr | None) -> str | None:
        """Return the name a string constraint uses for this column, if explicit.

        Recognizes ``mapped_column("name", ...)`` / ``mapped_column(name="name")``,
        and SQLModel's ``Field(sa_column=Column("name", ...))`` /
        ``Field(sa_column_kwargs={"name": "name"})``. SQLAlchemy resolves a
        constraint's string column through the column *key*, which defaults to
        the name, so an explicit ``key=`` takes precedence.
        """
        if value is None:
            return None
        if is_call_to(value, "mapped_column") or is_call_to(value, "Column"):
            for kw in value.keywords:
                if (
                    kw.arg == "key"
                    and isinstance(kw.value, ast.Constant)
                    and isinstance(kw.value.value, str)
                ):
                    return kw.value.value
            if (
                value.args
                and isinstance(value.args[0], ast.Constant)
                and isinstance(value.args[0].value, str)
            ):
                return value.args[0].value
            for kw in value.keywords:
                if (
                    kw.arg == "name"
                    and isinstance(kw.value, ast.Constant)
                    and isinstance(kw.value.value, str)
                ):
                    return kw.value.value
            return None
        if is_call_to(value, "Field"):
            for kw in value.keywords:
                if kw.arg == "sa_column":
                    return cls._explicit_column_name(kw.value)
                if kw.arg == "sa_column_kwargs" and isinstance(kw.value, ast.Dict):
                    opts = {
                        key.value: val.value
                        for key, val in zip(kw.value.keys, kw.value.values)
                        if isinstance(key, ast.Constant)
                        and isinstance(val, ast.Constant)
                        and isinstance(val.value, str)
                    }
                    # As above: an explicit key wins over the name.
                    found = opts.get("key", opts.get("name"))
                    if isinstance(found, str):
                        return found
        return None

    @classmethod
    def _table_args_unique_columns(cls, class_node: ast.ClassDef) -> Tuple[set[str], set[str]]:
        """Columns made unique on their own by the class's ``__table_args__``.

        Recognizes ``UniqueConstraint("col")`` and ``Index("name", "col",
        unique=True)`` with exactly one column, in a tuple/list ``__table_args__``
        (a trailing options dict is ignored). Composite constraints and partial
        indexes (``*_where=``) do not make a column unique and are skipped.

        Returns ``(db_columns, attribute_refs)``: a string names the *database*
        column, while a bare reference (``UniqueConstraint(account_id)``) names
        the attribute declared earlier in the class body.
        """
        value: ast.expr | None = None
        for node in class_node.body:
            if isinstance(node, ast.Assign):
                if any(isinstance(t, ast.Name) and t.id == "__table_args__" for t in node.targets):
                    value = node.value
            elif (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id == "__table_args__"
            ):
                value = node.value
        columns: set[str] = set()
        refs: set[str] = set()
        if not isinstance(value, (ast.Tuple, ast.List)):
            return columns, refs

        for item in value.elts:
            if is_call_to(item, "UniqueConstraint"):
                cols = item.args
            elif is_call_to(item, "Index"):
                if not any(
                    kw.arg == "unique" and isinstance(kw.value, ast.Constant) and kw.value.value
                    for kw in item.keywords
                ):
                    continue
                # A partial index (postgresql_where=, sqlite_where=, ...) is only
                # unique over a subset of rows, so it does not imply a 1:1. A
                # literal `*_where=None` is "no predicate", i.e. not partial.
                if any(
                    kw.arg
                    and kw.arg.endswith("_where")
                    and not (isinstance(kw.value, ast.Constant) and kw.value.value is None)
                    for kw in item.keywords
                ):
                    continue
                cols = item.args[1:]  # first positional arg is the index name
            else:
                continue
            if len(cols) == 1:
                col = cols[0]
                if isinstance(col, ast.Constant) and isinstance(col.value, str):
                    columns.add(col.value)
                elif isinstance(col, ast.Name):
                    refs.add(col.id)
        return columns, refs


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
