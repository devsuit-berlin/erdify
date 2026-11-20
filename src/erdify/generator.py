"""ERD diagram generators (PlantUML, Mermaid, JSON and an HTML preview)."""

import html
import json
import re
from typing import Dict, List, Set, Tuple

from .config import EntityInfo, EnumInfo, FieldInfo, is_sole_primary_key
from .edges import diagram_edges

#: Pinned Mermaid CDN major version used by the HTML preview format.
MERMAID_CDN = "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"

#: Version of the ``--format json`` document shape. Adding keys does not bump it;
#: removing or renaming a key, or changing a value's type or meaning, does.
JSON_SCHEMA_VERSION = 1


class _ERGenerator:
    """Shared ERD rendering: entity/enum bookkeeping and relationship lines.

    The edges come from :func:`erdify.edges.diagram_edges`; their crow's-foot
    glyphs (``}o--||``, ``||--o{``, ``||--||``, ``}o--o{``) are valid in *both*
    PlantUML and Mermaid, so subclasses share the relationship lines and only
    differ in names and entity/enum block formatting.
    """

    def __init__(
        self,
        entities: Dict[str, EntityInfo],
        enums: Dict[str, EnumInfo] | None = None,
        *,
        title: str = "Database ERD",
        include_relationships: bool = True,
    ):
        self.entities = entities
        self.enums = enums or {}
        self.title = title
        self.include_relationships = include_relationships
        self._ids: Dict[Tuple[str, str], str] | None = None
        self._table_schemas: Dict[str, Set[str | None]] | None = None

    # -- Names in the diagram source (#288) ---------------------------------
    #
    # Entity and enum names come from the model source, and a SQL table can be
    # called anything (``"Order Items"``). Each format turns a name into an
    # identifier its grammar accepts (``_identifier``, made unique across
    # entities and enums) and writes references to it (``_render_ref``) and
    # quoted labels (``_label``) its own way. The IR and JSON keep real names.

    def _identifier(self, name: str) -> str:
        """The bare diagram identifier for an entity or enum ``name``."""
        return name

    def _render_ref(self, identifier: str) -> str:
        """How a reference to ``identifier`` is written (e.g. quoted)."""
        return identifier

    def _label(self, text: str) -> str:
        """A quoted relationship label."""
        return f'"{text}"'

    def _diagram_ids(self) -> Dict[Tuple[str, str], str]:
        """``("entity" | "enum", name)`` -> unique diagram identifier.

        A name the format accepts as it is keeps it; an encoded name that
        collides with another one gets a ``_2``, ``_3``, ... suffix. Entities
        are numbered before enums, each in diagram order. Keyed by
        ``EntityInfo.name`` / ``EnumInfo.name`` (:meth:`_ref` resolves a dict
        key first); built once per :meth:`generate` call.
        """
        if self._ids is None:
            entity_names = [e.name for e in self.entities.values()]
            enum_names = [self.enums[n].name for n in sorted(self._get_used_enums())]
            keys = [("entity", name) for name in dict.fromkeys(entity_names)]
            keys += [("enum", name) for name in dict.fromkeys(enum_names)]
            encoded = {key: self._identifier(key[1]) for key in keys}
            ids: Dict[Tuple[str, str], str] = {}
            taken: set[str] = set()
            for key in keys:
                if encoded[key] == key[1] and key[1] not in taken:
                    ids[key] = key[1]
                    taken.add(key[1])
            for key in keys:
                if key in ids:
                    continue
                candidate, n = encoded[key], 2
                while candidate in taken:
                    candidate, n = f"{encoded[key]}_{n}", n + 1
                ids[key] = candidate
                taken.add(candidate)
            self._ids = ids
        return self._ids

    def _ref(self, entity_name: str, kind: str = "entity") -> str:
        """The diagram reference to an entity (or enum) called ``entity_name``.

        ``entity_name`` may also be a key of ``entities`` / ``enums`` (a
        relationship target), which a caller's dict may hold apart from the name.
        """
        index = self.entities if kind == "entity" else self.enums
        if entity_name in index:
            entity_name = index[entity_name].name
        return self._render_ref(self._diagram_ids()[(kind, entity_name)])

    def _edge(self, left: str, glyph: str, right: str, label: str) -> str:
        """One relationship line between the entities ``left`` and ``right``."""
        return f"{self._ref(left)} {glyph} {self._ref(right)} : {self._label(label)}"

    def _get_used_enums(self) -> "set[str]":
        """Get set of enum names used by entity fields."""
        used_enums: set[str] = set()
        for entity in self.entities.values():
            for field in entity.fields:
                type_name = field.type_str.split(".")[-1]
                if type_name in self.enums:
                    used_enums.add(type_name)
        return used_enums

    def _relationship_lines(self) -> List[str]:
        """One line per edge of :func:`diagram_edges`, in its order.

        Empty when the generator was built with ``include_relationships=False``
        (``--no-relationships``, #232).
        """
        if not self.include_relationships:
            return []
        return [
            self._edge(edge.from_entity, edge.glyph, edge.to_entity, edge.label)
            for edge in diagram_edges(self.entities)
        ]


class PlantUMLGenerator(_ERGenerator):
    """Generates a PlantUML ERD diagram from entities.

    Public API: the constructor and :meth:`generate`.

    Args:
        entities: Entity name to EntityInfo, as returned by the parsers.
        enums: Optional enum name to EnumInfo.
        title: Diagram title.
        include_relationships: Draw relationship lines (``False`` omits the
            whole ``' Relationships`` section).
    """

    def _identifier(self, name: str) -> str:
        """One word: other characters become ``_`` (``Order Items`` -> ``Order_Items``)."""
        return re.sub(r"\W+", "_", name) or "_"

    @staticmethod
    def _text(text: str) -> str:
        """Text on one line: ``"`` and ``<`` (markup) as ``&#34;`` / ``&#60;``.

        A control character (line break) becomes a space.
        """
        text = re.sub(r"[\x00-\x1f\x7f]", " ", text)
        return text.replace('"', "&#34;").replace("<", "&#60;")

    def _label(self, text: str) -> str:
        """A quoted relationship label."""
        return f'"{self._text(text)}"'

    def generate(self) -> str:
        """Render the diagram.

        Returns:
            PlantUML source, from ``@startuml`` to ``@enduml``.
        """
        self._ids = None  # the entities may have changed since the last call
        self._table_schemas = None
        lines = [
            f"@startuml {self.title}",
            '!define Table(name,desc) class name as "desc" << (T,#FFAAAA) >>',
            "!define primary_key(x) <b><color:#b8861b><&key></color> x</b>",
            "!define foreign_key(x) <color:#aaaaaa><&key></color> x",
            "!define column(x) <color:#efefef><&media-record></color> x",
            "",
            "skinparam linetype ortho",
            "skinparam roundcorner 5",
            "skinparam class {",
            "    BackgroundColor White",
            "    ArrowColor Gray",
            "    BorderColor Gray",
            "}",
            "",
        ]

        used_enums = self._get_used_enums()
        if used_enums:
            lines.append("' Enums")
            lines.append("")
            for enum_name in sorted(used_enums):
                if enum_name in self.enums:
                    lines.extend(self._generate_enum(self.enums[enum_name]))
                    lines.append("")

        lines.append("' Entities")
        lines.append("")
        for entity in self.entities.values():
            lines.extend(self._generate_entity(entity))
            lines.append("")

        if self.include_relationships:
            lines.append("' Relationships")
            lines.append("")
            lines.extend(self._relationship_lines())
            lines.append("")

        lines.append("@enduml")

        return "\n".join(lines)

    def _title(self, entity: EntityInfo) -> str:
        """The box title: the table name, ``schema.table`` when the name is in several schemas.

        Same-name tables in different schemas are told apart (#353): an
        entity named ``schema.table`` (SQL) keeps that title even when the
        other table is excluded; otherwise a table name is qualified when the
        entities drawing it are in more than one schema (no schema counts as
        one), compared without regard to case, as SQL folds unquoted names.
        """
        qualified = f"{entity.schema}.{entity.table_name}" if entity.schema else None
        if entity.name == qualified:
            return entity.name
        if self._table_schemas is None:
            self._table_schemas = {}
            for e in self.entities.values():
                self._table_schemas.setdefault(e.table_name.lower(), set()).add(e.schema)
        if qualified and len(self._table_schemas[entity.table_name.lower()]) > 1:
            return qualified
        return entity.table_name

    def _generate_entity(self, entity: EntityInfo) -> List[str]:
        """Generate PlantUML entity definition."""
        lines = []
        head = f'entity "{self._text(self._title(entity))}" as {self._ref(entity.name)}'
        if entity.is_link_table:
            lines.append(f"{head} << (L, #AAFFAA) link >> {{")
        else:
            lines.append(f"{head} {{")

        if entity.fields:
            for field in entity.fields:
                lines.append(f"  {self._format_field(field, entity.fields)}")
        else:
            lines.append("  ' (no fields)")

        lines.append("}")
        return lines

    def _generate_enum(self, enum_info: EnumInfo) -> List[str]:
        """Generate PlantUML enum definition."""
        alias = self._ref(enum_info.name, "enum")
        head = alias if alias == enum_info.name else f'"{self._text(enum_info.name)}" as {alias}'
        lines = [f"enum {head} << (E,#FFCC00) >> {{"]
        for value in enum_info.values:
            lines.append(f"  {self._text(value)}")
        lines.append("}")
        return lines

    def _format_field(self, field: FieldInfo, fields: List[FieldInfo]) -> str:
        """Format a field for PlantUML; ``fields`` are the entity's columns."""
        if field.is_primary_key:
            prefix = "primary_key"
        elif field.is_foreign_key:
            prefix = "foreign_key"
        else:
            prefix = "column"

        type_str = field.type_str.split(".")[-1]
        nullable = "?" if field.is_nullable else ""

        default = ""
        if field.default_value is not None:
            default_val = field.default_value
            if "." in default_val:
                default_val = default_val.split(".")[-1]
            default = f" = {self._text(default_val)}"

        # A sole primary key is unique by being the key; a composite member
        # that is unique on its own shows UK (#331).
        unique = " UK" if field.is_unique and not is_sole_primary_key(field, fields) else ""
        name = self._text(field.name)
        if name != field.name or any(c in name for c in ",()"):
            # A macro argument: quoted, it may hold a comma or parenthesis.
            name = f'"{name}"'

        # Omit the type suffix entirely when the type is unknown (e.g. an
        # untyped Core Column on a synthesized link table) to avoid a dangling ":".
        if not type_str:
            return f"{prefix}({name}){unique}"

        return f"{prefix}({name}) : {type_str}{nullable}{default}{unique}"


class MermaidGenerator(_ERGenerator):
    """Generates a Mermaid ``erDiagram`` from entities.

    Public API: the constructor and :meth:`generate`.

    Args:
        entities: Entity name to EntityInfo, as returned by the parsers.
        enums: Optional enum name to EnumInfo.
        title: Accepted for a uniform API; Mermaid ``erDiagram`` has no title.
        include_relationships: Draw relationship lines.
    """

    # The grammar these mirror is Mermaid 11's ``erDiagram`` lexer. Its
    # character classes are ASCII plus everything from U+00C0 (attributes) or
    # U+0080 (entities) up, and its ``\b`` is ASCII-only, hence ``_NOT_WORD``.
    _NOT_WORD = r"(?![0-9A-Za-z_])"
    #: An entity name Mermaid reads unquoted ...
    _BARE_ENTITY = re.compile(r"[0-9A-Za-z_\u0080-\U0010ffff][-0-9A-Za-z_\u0080-\U0010ffff]*")
    #: ... unless it starts with a keyword (``one``, ``to``, ``class``, ...).
    _ENTITY_KEYWORD = re.compile(
        r"(?:erdiagram|style|classdef|class|one|many|to|u|1|acctitle|accdescr)" + _NOT_WORD,
        re.IGNORECASE,
    )
    #: An attribute name or type, which must not start with a key (``PK``).
    _ATTRIBUTE_CHARS = r"-*0-9A-Za-z_\[\]()\u00c0-\U0010ffff"
    _ATTRIBUTE_WORD = re.compile(rf"[*A-Za-z_\u00c0-\U0010ffff][{_ATTRIBUTE_CHARS}]*")
    _ATTRIBUTE_KEY = re.compile(r"(?:pk|fk|uk)" + _NOT_WORD, re.IGNORECASE)
    #: Characters quoted text writes as Mermaid entity codes, which it decodes
    #: when drawing: a quote or ``%`` / backslash (not allowed in a quoted
    #: entity name), markup, ``#`` (starts a code) and ``~`` (a generic type
    #: inside an entity block, even within quotes).
    _CODES = {
        "#": "#35;",
        '"': "#quot;",
        "%": "#37;",
        "\\": "#92;",
        "&": "#38;",
        "<": "#lt;",
        ">": "#gt;",
        "~": "#126;",
    }
    #: A layout statement Mermaid finds even in a quoted entity name; written
    #: as codes in all quoted text, which draws the same.
    _DIRECTION = re.compile(r"(direction)(\s+)(?=(?:tb|bt|rl|lr))", re.IGNORECASE)

    def _identifier(self, name: str) -> str:
        """The entity name as quoted text (:meth:`_text`)."""
        return self._text(name) or "_"

    def _render_ref(self, identifier: str) -> str:
        """Unquoted when Mermaid reads the name as one word, quoted otherwise."""
        if self._BARE_ENTITY.fullmatch(identifier) and not self._ENTITY_KEYWORD.match(identifier):
            return identifier
        return f'"{identifier}"'

    def _label(self, text: str) -> str:
        """A quoted relationship label."""
        return f'"{self._text(text)}"'

    @classmethod
    def _text(cls, text: str) -> str:
        """Text for inside double quotes, drawn as it is: ``R&D "x"`` -> ``R#38;D #quot;x#quot;``.

        A control character (line break) becomes a space, and each space in
        ``direction TB`` (``LR``, ...) the code ``#32;``.
        """
        text = re.sub(r"[\x00-\x1f\x7f]", " ", text)
        text = "".join(cls._CODES.get(c, c) for c in text)
        return cls._DIRECTION.sub(lambda m: m.group(1) + "#32;" * len(m.group(2)), text)

    @classmethod
    def _attribute_word(cls, name: str) -> str:
        """``name`` as an attribute word: ``Author Key`` -> ``Author_Key``, ``1st`` -> ``_1st``.

        Characters Mermaid doesn't allow become ``_``; a name starting with a
        digit or hyphen, or with a key (``pk``), gets a leading ``_``.
        """
        if cls._ATTRIBUTE_WORD.fullmatch(name) and not cls._ATTRIBUTE_KEY.match(name):
            return name
        word = re.sub(rf"[^{cls._ATTRIBUTE_CHARS}]+", "_", name)
        if not cls._ATTRIBUTE_WORD.fullmatch(word) or cls._ATTRIBUTE_KEY.match(word):
            word = "_" + word
        return word

    def generate(self) -> str:
        """Render the diagram.

        Returns:
            Mermaid ``erDiagram`` source.
        """
        self._ids = None  # the entities may have changed since the last call
        self._table_schemas = None
        lines = ["erDiagram"]

        for entity in self.entities.values():
            lines.extend(self._generate_entity(entity))

        # Enums have no native Mermaid construct; render each used one as an
        # entity block listing its values so the values stay visible.
        for enum_name in sorted(self._get_used_enums()):
            if enum_name in self.enums:
                lines.extend(self._generate_enum(self.enums[enum_name]))

        for rel in self._relationship_lines():
            lines.append(f"    {rel}")

        return "\n".join(lines)

    def _generate_entity(self, entity: EntityInfo) -> List[str]:
        """Generate a Mermaid entity block."""
        lines = [f"    {self._ref(entity.name)} {{"]
        for field in entity.fields:
            lines.append(f"        {self._format_attr(field, entity.fields)}")
        lines.append("    }")
        return lines

    def _generate_enum(self, enum_info: EnumInfo) -> List[str]:
        """Render an enum as a Mermaid entity block listing its values."""
        lines = [f"    {self._ref(enum_info.name, 'enum')} {{"]
        for value in enum_info.values:
            word = self._attribute_word(value)
            comment = "" if word == value else f' "{self._text(value)}"'
            lines.append(f"        enum {word}{comment}")
        lines.append("    }")
        return lines

    def _format_attr(self, field: FieldInfo, fields: List[FieldInfo]) -> str:
        """Format a Mermaid attribute line: ``<type> <name> [keys] ["comment"]``.

        ``fields`` are the entity's columns.
        """
        type_token = self._mermaid_type(field.type_str)

        keys = []
        if field.is_primary_key:
            keys.append("PK")
        if field.is_foreign_key:
            keys.append("FK")
        if field.is_unique and not is_sole_primary_key(field, fields):  # #331
            keys.append("UK")
        key_str = ",".join(keys)

        name = self._attribute_word(field.name)
        comment_parts = [] if name == field.name else [field.name]
        if field.is_nullable:
            comment_parts.append("nullable")
        if field.default_value is not None:
            default_val = field.default_value
            if "." in default_val:
                default_val = default_val.split(".")[-1]
            comment_parts.append(f"default {default_val}")

        parts = [type_token, name]
        if key_str:
            parts.append(key_str)
        line = " ".join(parts)
        if comment_parts:
            line += f' "{self._text(", ".join(comment_parts))}"'
        return line

    @staticmethod
    def _mermaid_type(type_str: str) -> str:
        """Reduce a type to a single Mermaid-safe token.

        Mermaid attribute types must be a single token, so spaces, pipes and
        brackets (e.g. ``list[str]``) are collapsed to underscores.
        """
        cleaned = type_str.split(".")[-1]
        token = re.sub(r"[^0-9A-Za-z_]+", "_", cleaned).strip("_")
        return MermaidGenerator._attribute_word(token or "unknown")


def generate_plantuml(
    entities: Dict[str, EntityInfo],
    enums: Dict[str, EnumInfo] | None = None,
    *,
    title: str = "Database ERD",
    include_enums: bool = True,
    include_relationships: bool = True,
) -> str:
    """
    Generate a PlantUML ERD diagram from parsed entities.

    Args:
        entities: Dictionary of entity name to EntityInfo
        enums: Optional dictionary of enum name to EnumInfo
        title: Title for the diagram
        include_enums: Whether to include enum definitions
        include_relationships: Whether to include relationship lines

    Returns:
        PlantUML diagram as string
    """
    generator = PlantUMLGenerator(
        entities=entities,
        enums=enums if include_enums else None,
        title=title,
        include_relationships=include_relationships,
    )
    return generator.generate()


def generate_mermaid(
    entities: Dict[str, EntityInfo],
    enums: Dict[str, EnumInfo] | None = None,
    *,
    title: str = "Database ERD",
    include_enums: bool = True,
    include_relationships: bool = True,
) -> str:
    """
    Generate a Mermaid ``erDiagram`` from parsed entities.

    Args:
        entities: Dictionary of entity name to EntityInfo
        enums: Optional dictionary of enum name to EnumInfo
        title: Unused (Mermaid erDiagram has no title); accepted for a uniform API
        include_enums: Whether to render used enums as entity blocks
        include_relationships: Whether to include relationship lines

    Returns:
        Mermaid erDiagram as string
    """
    generator = MermaidGenerator(
        entities=entities,
        enums=enums if include_enums else None,
        title=title,
        include_relationships=include_relationships,
    )
    return generator.generate()


def generate_json(
    entities: Dict[str, EntityInfo],
    enums: Dict[str, EnumInfo] | None = None,
    *,
    title: str = "Database ERD",
    include_enums: bool = True,
    include_relationships: bool = True,
) -> str:
    """
    Serialize the parsed model as JSON (a stable, documented schema).

    Shape: ``{schema_version, title, entities: [{name, table_name, schema, source, module, app,
    is_link_table,
    fields: [{name, type, primary_key, foreign_key, nullable, foreign_table,
    index, unique, default}], relationships: [{target, type, attribute, nullable,
    inverse}]}],
    edges: [{from_entity, to_entity, from_end: {optional, many}, to_end, label, kind}],
    enums:
    [{name, values}]}``. Downstream tools can consume this without re-parsing.
    ``schema_version`` is :data:`JSON_SCHEMA_VERSION`; consumers should ignore
    keys they do not know. The full schema is documented in
    ``docs/usage/output-formats.md`` and published as a JSON Schema,
    ``docs/schema/output-v1.json``.

    Args:
        entities: Dictionary of entity name to EntityInfo
        enums: Optional dictionary of enum name to EnumInfo
        title: Value of the ``title`` key
        include_enums: Whether to fill ``enums`` (otherwise ``[]``)
        include_relationships: Whether to fill each entity's ``relationships``
            and ``edges`` (otherwise ``[]``)

    Returns:
        The JSON document as an indented string
    """
    model = {
        "schema_version": JSON_SCHEMA_VERSION,
        "title": title,
        "entities": [
            {
                "name": entity.name,
                "table_name": entity.table_name,
                "schema": entity.schema,
                "source": entity.source,
                "module": entity.module,
                "app": entity.app,
                "is_link_table": entity.is_link_table,
                "fields": [
                    {
                        "name": f.name,
                        "type": f.type_str,
                        "primary_key": f.is_primary_key,
                        "foreign_key": f.is_foreign_key,
                        "nullable": f.is_nullable,
                        "foreign_table": f.foreign_table,
                        "index": f.index,
                        "unique": f.is_unique,
                        "default": f.default_value,
                    }
                    for f in entity.fields
                ],
                "relationships": (
                    [
                        {
                            "target": target,
                            "type": rel_type,
                            "attribute": attr,
                            "nullable": rel_type == "one" and attr in entity.nullable_relationships,
                            "inverse": entity.inverse_relationships.get(attr),
                        }
                        for target, rel_type, attr in entity.relationships
                    ]
                    if include_relationships
                    else []
                ),
            }
            for entity in entities.values()
        ],
        "edges": (
            [
                {
                    "from_entity": edge.from_entity,
                    "to_entity": edge.to_entity,
                    "from_end": {"optional": edge.from_end.optional, "many": edge.from_end.many},
                    "to_end": {"optional": edge.to_end.optional, "many": edge.to_end.many},
                    "label": edge.label,
                    "kind": edge.kind,
                }
                for edge in diagram_edges(entities)
            ]
            if include_relationships
            else []
        ),
        "enums": (
            [{"name": e.name, "values": e.values} for e in (enums or {}).values()]
            if include_enums
            else []
        ),
    }
    return json.dumps(model, indent=2)


def generate_html(
    entities: Dict[str, EntityInfo],
    enums: Dict[str, EnumInfo] | None = None,
    *,
    title: str = "Database ERD",
    include_enums: bool = True,
    include_relationships: bool = True,
) -> str:
    """
    Render a self-contained HTML page that draws the ERD with Mermaid.

    The page loads Mermaid from a pinned CDN (``MERMAID_CDN``), so it needs
    internet access to render. Open it in a browser to view the diagram. The
    diagram source is HTML-escaped (a name may hold ``<`` or ``&``); Mermaid
    decodes it before parsing.

    Args:
        entities: Dictionary of entity name to EntityInfo
        enums: Optional dictionary of enum name to EnumInfo
        title: Page ``<title>`` and heading (HTML-escaped)
        include_enums: Whether to render used enums as entity blocks
        include_relationships: Whether to include relationship lines

    Returns:
        A complete HTML document as string
    """
    diagram = generate_mermaid(
        entities,
        enums,
        title=title,
        include_enums=include_enums,
        include_relationships=include_relationships,
    )
    safe_title = html.escape(title)
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"  <title>{safe_title}</title>\n"
        f'  <script src="{MERMAID_CDN}"></script>\n'
        "  <style>body{font-family:system-ui,sans-serif;margin:2rem;color:#222}"
        "h1{font-size:1.1rem;color:#555;font-weight:600}</style>\n"
        "</head>\n"
        "<body>\n"
        f"  <h1>{safe_title}</h1>\n"
        '  <pre class="mermaid">\n'
        f"{html.escape(diagram, quote=False)}\n"
        "  </pre>\n"
        "  <script>mermaid.initialize({ startOnLoad: true });</script>\n"
        "</body>\n"
        "</html>\n"
    )
