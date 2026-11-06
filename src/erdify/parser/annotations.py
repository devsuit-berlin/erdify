"""Pure helpers that read type annotations from the syntax tree.

Shared by every dialect: model references (#229), column types and
nullability (#236), and call / wrapper recognition.
"""

import ast
from typing import Callable, List, Mapping, NamedTuple, Tuple, TypeGuard

from .common import _Rel


class _AnnotationRef(NamedTuple):
    """A single model an annotation refers to (see :func:`annotation_reference`)."""

    target: str
    many: bool
    nullable: bool
    #: Named through a module (``schemas.User``); only trusted in relationship().
    qualified: bool = False
    #: The name as written (``a.User``); tells same-named classes apart in a union.
    spelled: str = ""


#: Wrappers whose first argument is the annotated type itself (metadata ignored).
TRANSPARENT_WRAPPERS = frozenset({"Mapped", "Annotated"})
#: SQLAlchemy wrappers that only annotate collections: ``WriteOnlyMapped["X"]``.
MANY_WRAPPERS = frozenset({"WriteOnlyMapped", "DynamicMapped"})
#: SQLAlchemy 2.0 annotation wrappers that mark a mapped attribute.
MAPPED_WRAPPERS = frozenset({"Mapped"}) | MANY_WRAPPERS
#: Type qualifiers: they say how a field is declared, not what it holds, so a
#: column's type and nullability are those of the qualified type.
QUALIFIERS = frozenset({"Final", "InitVar", "Required", "NotRequired", "ReadOnly"})
#: Single-argument collections of a model: a "many" reference.
MANY_CONTAINERS = frozenset(
    {
        "list",
        "List",
        "set",
        "Set",
        "frozenset",
        "FrozenSet",
        "AbstractSet",
        "MutableSet",
        "Sequence",
        "MutableSequence",
        "Collection",
        "Iterable",
        "deque",
        "Deque",
    }
)
#: Mappings whose *value* is the model (e.g. SQLAlchemy keyed-dict collections).
MANY_MAPPINGS = frozenset({"dict", "Dict", "Mapping", "MutableMapping"})


def expr_name(node: ast.expr) -> str | None:
    """The last name of ``X`` or ``mod.X``; None for anything else."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def is_call_to(value: ast.expr, func_name: str) -> TypeGuard[ast.Call]:
    """Check whether an expression is a call to ``func_name`` (Name or attribute)."""
    if not isinstance(value, ast.Call):
        return False
    return expr_name(value.func) == func_name


def parse_quoted(node: ast.expr) -> ast.expr | None:
    """The expression inside a quoted annotation (``"User | None"``).

    None when ``node`` is not a string, or the string is not an expression.
    """
    if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
        return None
    try:
        return ast.parse(node.value.strip(), mode="eval").body
    except (SyntaxError, ValueError):  # ValueError: NUL byte on Python 3.11
        return None


def subscript_parts(node: ast.Subscript) -> Tuple[str | None, List[ast.expr]]:
    """``X[a, b]`` / ``mod.X[a, b]`` -> ``("X", [a, b])``."""
    args = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
    return expr_name(node.value), args


def is_none(node: ast.expr) -> bool:
    """``None``, ``NoneType`` (``types.NoneType``) or ``type(None)``.

    Also when quoted or wrapped in ``Annotated``.
    """
    if (
        isinstance(node, ast.Subscript)
        and expr_name(node.value) == "Annotated"
        and isinstance(node.slice, ast.Tuple)
        and node.slice.elts
    ):
        return is_none(node.slice.elts[0])
    if isinstance(node, ast.Constant):
        if node.value is None:
            return True
        parsed = parse_quoted(node)
        return parsed is not None and is_none(parsed)
    if isinstance(node, ast.Call):  # type(None)
        return (
            expr_name(node.func) == "type"
            and len(node.args) == 1
            and not node.keywords
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value is None
        )
    return expr_name(node) == "NoneType"


def column_type(node: ast.expr) -> Tuple[str, bool]:
    """A column's displayed type and whether its annotation admits ``None``.

    Walks the syntax tree like :func:`annotation_reference` (#236): the
    ``Mapped`` family, ``Annotated`` and type qualifiers such as ``Final``
    (bare or qualified) are unwrapped,
    and ``X | None``, ``None | X``, ``Optional[X]`` and ``Union[X, None]``
    all give ``X`` and nullable. A union of several other types keeps them,
    minus ``None``, in its own spelling; any member that is itself optional
    makes the column nullable. ``Literal[..., None]`` is nullable too. A
    quoted annotation is read like the unquoted one. Matching on the tree
    means a class merely *named* ``OptionalSettings`` or ``NoneableJSON``
    is not nullable.
    """
    if is_none(node):
        return "None", True
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        parsed = parse_quoted(node)
        return column_type(parsed) if parsed is not None else (node.value, False)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return column_union(union_operands(node), " | ".join)
    if isinstance(node, ast.Subscript):
        name, args = subscript_parts(node)
        if args and name in TRANSPARENT_WRAPPERS | MANY_WRAPPERS | QUALIFIERS:
            return column_type(args[0])
        if name == "Optional" and len(args) == 1:
            return column_type(args[0])[0], True
        if name == "Union" and args:
            prefix = ast.unparse(node.value)
            return column_union(args, lambda parts: f"{prefix}[{', '.join(parts)}]")
        if name == "Literal":
            return ast.unparse(node), literal_admits_none(args)
    return ast.unparse(node), False


def expand_aliases(
    node: ast.expr, aliases: Mapping[str, ast.expr], stack: Tuple[str, ...] = ()
) -> ast.expr:
    """``node`` with each column type alias replaced by its definition (#241).

    ``id: Mapped[intpk]`` with ``intpk = Annotated[int, mapped_column(...)]``
    reads as ``Mapped[Annotated[int, mapped_column(...)]]``, also when quoted
    (``Mapped["intpk"]``). Only type positions are expanded: ``Annotated``
    metadata, ``Literal`` values and call arguments (``ForeignKey("user.id")``)
    are left alone, and so is a subscripted (generic) alias such as
    ``Pk[int]``. An alias referring to itself is left as is. ``node`` itself
    is never modified.
    """
    if not aliases or not _mentions_alias(node, aliases):
        return node
    if isinstance(node, ast.Name):
        if node.id in aliases and node.id not in stack:
            return expand_aliases(aliases[node.id], aliases, stack + (node.id,))
        return node
    if isinstance(node, ast.Constant):
        parsed = parse_quoted(node)
        if parsed is None:
            return node
        expanded = expand_aliases(parsed, aliases, stack)
        return expanded if expanded is not parsed else node
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return ast.BinOp(
            left=expand_aliases(node.left, aliases, stack),
            op=node.op,
            right=expand_aliases(node.right, aliases, stack),
        )
    if isinstance(node, ast.Subscript):
        name, args = subscript_parts(node)
        if (
            not args
            or name == "Literal"
            or (isinstance(node.value, ast.Name) and node.value.id in aliases)
        ):
            return node
        # Annotated: only the type is a type position, not the metadata.
        parts: List[ast.expr] = [expand_aliases(args[0], aliases, stack)] + (
            args[1:]
            if name == "Annotated"
            else [expand_aliases(a, aliases, stack) for a in args[1:]]
        )
        slice_: ast.expr = (
            ast.Tuple(elts=parts, ctx=ast.Load()) if isinstance(node.slice, ast.Tuple) else parts[0]
        )
        return ast.Subscript(value=node.value, slice=slice_, ctx=node.ctx)
    return node


def _mentions_alias(node: ast.expr, aliases: Mapping[str, ast.expr]) -> bool:
    """Whether an alias name, or any string (a possible quoted alias), occurs in ``node``."""
    return any(
        (isinstance(sub, ast.Name) and sub.id in aliases)
        or (isinstance(sub, ast.Constant) and isinstance(sub.value, str))
        for sub in ast.walk(node)
    )


def defines_column_alias(value: ast.expr) -> bool:
    """``Annotated[X, ..., mapped_column(...), ...]``: an alias carrying column settings.

    Other ``Annotated`` aliases (e.g. Pydantic's ``PositiveInt = Annotated[int,
    Gt(0)]``) keep their name as the displayed type.
    """
    if not isinstance(value, ast.Subscript):
        return False
    name, args = subscript_parts(value)
    return name == "Annotated" and any(is_call_to(arg, "mapped_column") for arg in args[1:])


def column_metadata(node: ast.expr) -> List[ast.expr]:
    """The ``Annotated`` metadata that applies to a column, innermost first (#241).

    Follows the same wrappers as :func:`column_type`: ``Mapped`` and its
    variants, type qualifiers, quotes, and an optional type (``Optional[X]``,
    ``X | None``), but not a union of several types.
    """
    if isinstance(node, ast.Constant):
        parsed = parse_quoted(node)
        return column_metadata(parsed) if parsed is not None else []
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        rest = [option for option in union_operands(node) if not is_none(option)]
        return column_metadata(rest[0]) if len(rest) == 1 else []
    if not isinstance(node, ast.Subscript):
        return []
    name, args = subscript_parts(node)
    if not args:
        return []
    if name == "Annotated":
        return [*column_metadata(args[0]), *args[1:]]
    if name in TRANSPARENT_WRAPPERS | MANY_WRAPPERS | QUALIFIERS:
        return column_metadata(args[0])
    if name == "Optional" and len(args) == 1:
        return column_metadata(args[0])
    if name == "Union":
        rest = [option for option in args if not is_none(option)]
        return column_metadata(rest[0]) if len(rest) == 1 else []
    return []


def literal_admits_none(args: List[ast.expr]) -> bool:
    """``Literal[..., None]``, also nested (``Literal[Literal[None], "a"]``).

    The string ``"None"`` is a value, not ``None``.
    """
    for arg in args:
        if isinstance(arg, ast.Constant) and arg.value is None:
            return True
        if isinstance(arg, ast.Subscript):
            name, inner = subscript_parts(arg)
            if name == "Literal" and literal_admits_none(inner):
                return True
    return False


def column_union(options: List[ast.expr], spell: Callable[[List[str]], str]) -> Tuple[str, bool]:
    """A union column type without its ``None`` members; ``spell`` joins the rest.

    Each remaining member is resolved like a column of its own, so wrappers
    and quotes are dropped and a nested ``Optional`` still counts.
    """
    rest = [option for option in options if not is_none(option)]
    if not rest:  # `None | None`
        return "None", True
    members = [column_type(option) for option in rest]
    nullable = len(rest) < len(options) or any(inner for _, inner in members)
    if len(members) == 1:
        return members[0][0], nullable
    return spell([type_str for type_str, _ in members]), nullable


def annotation_reference(node: ast.expr, many: bool = False) -> _AnnotationRef | None:
    """The single class an annotation refers to, with cardinality and optionality.

    Walks the annotation's syntax tree, so every spelling of the same type
    resolves alike (#229): ``X | None`` / ``None | X``, ``Optional[X]``,
    ``Union[X, None]``, string forward references (also ``"None"``),
    ``Mapped`` / ``Annotated`` wrappers, ``typing.``-qualified forms,
    module-qualified classes (``schemas.User``, flagged ``qualified``),
    and collections: ``list``, ``set``, ``Sequence`` and friends,
    ``tuple[X, ...]``, a mapping's value type, and the collection-only
    ``WriteOnlyMapped`` / ``DynamicMapped``. Returns None when the
    annotation does not name exactly one class, such as
    ``Union[User, int]`` or ``tuple[User, int]``.
    """
    if isinstance(node, ast.Constant):
        parsed = parse_quoted(node)
        return annotation_reference(parsed, many) if parsed is not None else None
    if isinstance(node, ast.Name):
        return _AnnotationRef(node.id, many, False, spelled=node.id)
    if isinstance(node, ast.Attribute):
        return _AnnotationRef(node.attr, many, False, qualified=True, spelled=ast.unparse(node))
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return union_reference(union_operands(node), many)
    if not isinstance(node, ast.Subscript):
        return None
    name, args = subscript_parts(node)
    if not args:
        return None
    if name in TRANSPARENT_WRAPPERS:
        return annotation_reference(args[0], many)
    if name in MANY_WRAPPERS:
        return annotation_reference(args[0], True)
    if name == "Optional" and len(args) == 1:
        ref = annotation_reference(args[0], many)
        return ref._replace(nullable=True) if ref else None
    if name == "Union":
        return union_reference(args, many)
    if name in MANY_CONTAINERS and len(args) == 1:
        return annotation_reference(args[0], True)
    if name in ("tuple", "Tuple") and len(args) == 2:
        ellipsis = args[1]
        if isinstance(ellipsis, ast.Constant) and ellipsis.value is Ellipsis:
            return annotation_reference(args[0], True)
    if name in MANY_MAPPINGS and len(args) == 2:
        return annotation_reference(args[1], True)
    return None


def union_operands(node: ast.expr) -> List[ast.expr]:
    """Flatten ``A | B | C`` into its operands."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return [*union_operands(node.left), *union_operands(node.right)]
    return [node]


def union_reference(options: List[ast.expr], many: bool) -> _AnnotationRef | None:
    """Resolve a union whose members all name the same class, plus optional ``None``.

    Members are compared after resolving, so repeated or nested spellings
    of one type (``Union[User, User, None]``, ``Union[User, Optional[User]]``)
    resolve like ``Optional[User]``. Members naming different classes, or
    the same class once as one and once as many, name no single class.
    """
    rest = [option for option in options if not is_none(option)]
    refs = [annotation_reference(option, many) for option in rest]
    if not refs or any(ref is None for ref in refs):
        return None
    resolved = [ref for ref in refs if ref is not None]
    first = resolved[0]
    # Compare the full spelling: `a.User` and `b.User` are different classes.
    if any((ref.spelled, ref.many) != (first.spelled, first.many) for ref in resolved):
        return None
    nullable = len(rest) < len(options) or any(ref.nullable for ref in resolved)
    qualified = any(ref.qualified for ref in resolved)
    return first._replace(nullable=nullable, qualified=qualified)


def is_mapped_annotation(annotation: ast.expr) -> bool:
    """``Mapped[...]`` (or ``WriteOnlyMapped`` / ``DynamicMapped``), bare or qualified."""
    return isinstance(annotation, ast.Subscript) and expr_name(annotation.value) in MAPPED_WRAPPERS


def as_rel(ref: _AnnotationRef, attr: str) -> _Rel:
    """A relationship tuple; only a ``one`` reference can be optional (#223)."""
    return _Rel(ref.target, "many" if ref.many else "one", attr, ref.nullable and not ref.many)
