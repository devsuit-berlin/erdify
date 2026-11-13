"""Names a diagram grammar can't take as they are (#288).

Table, column, enum and relationship names come from the model source; a SQL
quoted identifier or a Django ``db_column`` can hold spaces, punctuation and
quotes, and a class can be called like a Mermaid keyword (``Class``). Every
format must still produce a diagram its renderer parses, and show the real
name where its grammar allows it. The expected encodings were checked with
Mermaid 11's parser and renderer and with PlantUML.
"""

from pathlib import Path

import pytest

from erdify.config import EntityInfo, EnumInfo, FieldInfo
from erdify.generator import (
    MermaidGenerator,
    generate_html,
    generate_json,
    generate_mermaid,
    generate_plantuml,
)
from erdify.parser import parse_models_directory

FIXTURES = Path(__file__).parent / "fixtures"


def _entity(name: str, *fields: FieldInfo, table: str | None = None) -> EntityInfo:
    return EntityInfo(name=name, table_name=table or name, fields=list(fields), source="sql")


def _pk(name: str = "id") -> FieldInfo:
    return FieldInfo(name=name, type_str="int", is_primary_key=True)


def _fk(name: str, table: str) -> FieldInfo:
    return FieldInfo(name=name, type_str="int", is_foreign_key=True, foreign_table=f"{table}.id")


@pytest.fixture(scope="module")
def catalog(tmp_path_factory: pytest.TempPathFactory) -> "tuple[dict, dict]":
    src = tmp_path_factory.mktemp("names")
    (src / "names.sql").write_text(
        (FIXTURES / "sql_edge_cases" / "diagram_names.sql").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return parse_models_directory(src, include_patterns=["*.sql"])


class TestMermaidAttributeNames:
    @pytest.mark.parametrize(
        ("name", "word"),
        [
            ("id", "id"),
            ("größe", "größe"),
            ("ref-x_[a](b)*", "ref-x_[a](b)*"),
            ("pk_id", "pk_id"),
            ("Item Key", "Item_Key"),
            ("a,b", "a_b"),
            ("naïve°", "naïve_"),
            ("1st", "_1st"),
            ("-x", "_-x"),
            ("(x)", "_(x)"),
            ("pk", "_pk"),
            ("UK", "_UK"),
            ("Fk-ref", "_Fk-ref"),
            ("pkä", "_pkä"),  # Mermaid's \b is ASCII-only: "pk" is a key here
            ("", "_"),
        ],
    )
    def test_attribute_word(self, name: str, word: str):
        assert MermaidGenerator._attribute_word(name) == word

    def test_encoded_name_keeps_the_real_one_as_comment(self, catalog):
        out = generate_mermaid(*catalog)
        assert 'int Item_Key PK "Item Key"' in out
        assert 'int _uk "uk, nullable"' in out
        assert 'int a_b UK "a#quot;b, nullable"' in out
        assert 'text größe "nullable, default ' in out  # valid as it is: no name in comment

    def test_type_token_is_an_attribute_word(self):
        assert MermaidGenerator._mermaid_type("3D") == "_3D"
        assert MermaidGenerator._mermaid_type("PK") == "_PK"
        assert MermaidGenerator._mermaid_type("list[str]") == "list_str"


class TestMermaidQuotedText:
    def test_codes_keep_every_character(self, catalog):
        out = generate_mermaid(*catalog)
        assert "default 'x #quot;y#quot; #126;z#126;'" in out
        assert '"a#126;b#126;c, nullable"' in out
        assert '"100#37; done, nullable"' in out
        assert ': "a#quot;b"' in out

    def test_direction_statement_is_broken_up(self, catalog):
        out = generate_mermaid(*catalog)
        assert '"direction#32;LR, nullable"' in out
        assert '"direction#32;TB" {' in out

    def test_line_break_becomes_space(self):
        field = FieldInfo(name="x", type_str="str", default_value="'a\nb'")
        out = generate_mermaid({"A": _entity("A", field)})
        assert "default 'a b'" in out

    def test_markup_is_coded(self):
        out = generate_mermaid({"R&D <x>": _entity("R&D <x>", _pk())})
        assert '"R#38;D #lt;x#gt;" {' in out


class TestMermaidEntityNames:
    @pytest.mark.parametrize(
        "name", ["User", "Größe", "Line-Note", "1st", "Classroom", "Ones", "many_x", "Only"]
    )
    def test_bare(self, name: str):
        out = generate_mermaid({name: _entity(name, _pk())})
        assert f"    {name} {{" in out

    @pytest.mark.parametrize(
        "name",
        ["Order Items", "Class", "Style", "classDef", "One", "many", "To", "to-do", "U", "1"]
        + ["erDiagram", "accTitle", "a.b", "-x"],
    )
    def test_quoted(self, name: str):
        out = generate_mermaid({name: _entity(name, _pk())})
        assert f'    "{name}" {{' in out

    def test_relationship_uses_the_same_reference(self, catalog):
        out = generate_mermaid(*catalog)
        assert 'Line-Note }o--o| "Order Items" : "Item Key"' in out
        assert '"Class" }o--o| "one" : "one"' in out
        assert '"direction#32;TB" }o--o| "a#37;b#92;c" : "x"' in out

    def test_python_model_named_like_a_keyword(self):
        entities, enums = parse_models_directory(
            FIXTURES / "django_edge_cases", include_patterns=["diagram_names.py"]
        )
        out = generate_mermaid(entities, enums)
        assert '"Class" {' in out
        assert 'str Class_Title "Class Title"' in out
        assert 'int Owner_(ID) FK "Owner (ID)"' in out
        assert '"Style" }o--|| "Class" : "Owner (ID)"' in out

    def test_enum_block_and_values(self):
        field = FieldInfo(name="state", type_str="order state")
        enum = EnumInfo(name="order state", values=["new", "in progress", "1st"])
        out = generate_mermaid({"A": _entity("A", field)}, {"order state": enum})
        assert '    "order state" {' in out
        assert "        enum new\n" in out
        assert '        enum in_progress "in progress"' in out
        assert '        enum _1st "1st"' in out

    def test_entity_and_enum_of_the_same_name(self):
        field = FieldInfo(name="status", type_str="Status")
        out = generate_mermaid(
            {"Status": _entity("Status", _pk()), "A": _entity("A", field)},
            {"Status": EnumInfo(name="Status", values=["a"])},
        )
        assert "    Status {" in out
        assert "    Status_2 {" in out


class TestPlantUML:
    def test_alias_is_one_word_display_name_is_real(self, catalog):
        out = generate_plantuml(*catalog)
        assert 'entity "Order Items" as Order_Items {' in out
        assert 'entity "Line-Note" as Line_Note {' in out
        assert 'entity "Größe" as Größe {' in out
        assert 'Line_Note }o--o| Order_Items : "Item Key"' in out

    def test_colliding_aliases_are_numbered(self, catalog):
        out = generate_plantuml(*catalog)
        assert 'entity "a_b" as a_b {' in out  # a valid name keeps its alias
        assert 'entity "a b" as a_b_2 {' in out
        assert 'a_b_2 }o--o| a_b : "a_b"' in out
        assert 'a_b }o--o| a_b_2 : "a b"' in out

    def test_column_macro_argument(self, catalog):
        out = generate_plantuml(*catalog)
        assert "primary_key(Item Key) : int" in out
        assert 'column("a,b") : int?' in out
        assert 'column("(x)") : text?' in out
        assert 'column("a&#34;b") : int? UK' in out
        assert 'foreign_key("a&#34;b") : int?' in out
        assert ': "a&#34;b"' in out

    def test_markup_is_escaped(self):
        field = FieldInfo(name="a<b>", type_str="str", default_value="'<i>'")
        out = generate_plantuml({"T": _entity("T", field, table="R&D <x>")})
        assert 'entity "R&D &#60;x>" as T {' in out
        assert "column(\"a&#60;b>\") : str = '&#60;i>'" in out

    def test_enum_alias(self):
        field = FieldInfo(name="state", type_str="order state")
        enum = EnumInfo(name="order state", values=["in progress"])
        out = generate_plantuml({"A": _entity("A", field)}, {"order state": enum})
        assert 'enum "order state" as order_state << (E,#FFCC00) >> {' in out
        assert "  in progress\n" in out

    def test_entity_and_enum_of_the_same_name(self):
        field = FieldInfo(name="status", type_str="Status")
        out = generate_plantuml(
            {"Status": _entity("Status", _pk()), "A": _entity("A", field)},
            {"Status": EnumInfo(name="Status", values=["a"])},
        )
        assert 'enum "Status" as Status_2 << (E,#FFCC00) >> {' in out
        assert 'entity "Status" as Status {' in out


class TestOtherFormats:
    def test_html_escapes_the_diagram(self):
        out = generate_html({"R&D <x>": _entity("R&D <x>", _pk())})
        assert '"R#38;D #lt;x#gt;" {' in out  # no raw markup reaches the page
        assert "<x>" not in out

    def test_json_keeps_real_names(self, catalog):
        out = generate_json(*catalog)
        assert '"name": "Order Items"' in out
        assert '"name": "a\\"b"' in out


def test_link_table_edges_use_references():
    link = _entity("order item", _fk("a b", "a b"), _fk("c", "c"))
    link.fields[0].is_primary_key = link.fields[1].is_primary_key = True
    link.is_link_table = True
    entities = {"a b": _entity("a b", _pk()), "c": _entity("c", _pk()), "order item": link}
    out = generate_mermaid(entities)
    assert '"a b" ||--o{ "order item" : "a b"' in out
    assert '"order item" }o--|| c : "c"' in out


class TestReviewFollowUps:
    def test_plantuml_line_break_becomes_space(self):
        field = FieldInfo(name="a\nb", type_str="str", default_value="'c\nd'")
        out = generate_plantuml({"T": _entity("T", field, table="x\ny")})
        assert 'entity "x y" as T {' in out
        assert "column(\"a b\") : str = 'c d'" in out

    def test_keys_that_differ_from_names(self):
        orders = _entity("Order", _pk(), _fk("user_id", "user"), table="orders")
        user = _entity("User", _pk(), table="user")
        entities = {"orders": orders, "users": user}
        for generate in (generate_plantuml, generate_mermaid):
            out = generate(entities)
            assert "Order }o--|| User" in out

    def test_generator_reused_after_adding_an_entity(self):
        entities = {"A": _entity("A", _pk())}
        gen = MermaidGenerator(entities)
        gen.generate()
        entities["B c"] = _entity("B c", _pk())
        assert '"B c" {' in gen.generate()
