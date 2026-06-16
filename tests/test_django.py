"""Tests for parsing Django ORM models (#36)."""

from pathlib import Path

from erdify.generator import PlantUMLGenerator
from erdify.parser import parse_models_directory


def _edges(output: str) -> list[frozenset[str]]:
    """Return the endpoint pairs of every PlantUML connector line."""
    pairs: list[frozenset[str]] = []
    for line in output.splitlines():
        if "--" not in line or ":" not in line:
            continue
        tokens = line.split(":", 1)[0].split()
        if len(tokens) >= 3:
            pairs.append(frozenset((tokens[0], tokens[-1])))
    return pairs


class TestDjangoEntities:
    def test_models_detected_as_entities(self, django_models_dir: Path):
        entities, _ = parse_models_directory(django_models_dir)

        for name in ("Author", "Profile", "Tag", "Post", "Group", "Membership", "Category"):
            assert name in entities

    def test_entities_have_django_source(self, django_models_dir: Path):
        entities, _ = parse_models_directory(django_models_dir)
        assert entities["Author"].source == "django"

    def test_abstract_base_not_an_entity(self, django_models_dir: Path):
        entities, _ = parse_models_directory(django_models_dir)
        assert "TimestampedModel" not in entities

    def test_abstract_base_fields_inherited(self, django_models_dir: Path):
        entities, _ = parse_models_directory(django_models_dir)
        author_fields = {f.name for f in entities["Author"].fields}
        assert "created_at" in author_fields
        assert "updated_at" in author_fields


class TestDjangoColumns:
    def test_column_types_mapped_to_python(self, django_models_dir: Path):
        """By default Django field types are mapped to readable Python types."""
        entities, _ = parse_models_directory(django_models_dir)
        author_fields = {f.name: f for f in entities["Author"].fields}
        assert author_fields["name"].type_str == "str"  # CharField
        assert author_fields["bio"].type_str == "str"  # TextField
        assert author_fields["created_at"].type_str == "datetime"  # DateTimeField

    def test_unmapped_field_falls_back_to_django_name(self, django_models_dir: Path):
        """Ambiguous/unknown fields keep their Django name rather than fake a type."""
        entities, _ = parse_models_directory(django_models_dir)
        profile_fields = {f.name: f for f in entities["Profile"].fields}
        assert profile_fields["preferences"].type_str == "JSONField"

    def test_implicit_id_primary_key_is_int(self, django_models_dir: Path):
        """Django's implicit id is a BigAutoField -> rendered as int by default."""
        entities, _ = parse_models_directory(django_models_dir)
        author_fields = {f.name: f for f in entities["Author"].fields}
        assert "id" in author_fields
        assert author_fields["id"].is_primary_key is True
        assert author_fields["id"].type_str == "int"


class TestDjangoRawTypes:
    """--django-raw-types keeps the original Django field class names."""

    def test_raw_column_types(self, django_models_dir: Path):
        entities, _ = parse_models_directory(django_models_dir, django_raw_types=True)
        author_fields = {f.name: f for f in entities["Author"].fields}
        assert author_fields["name"].type_str == "CharField"
        assert author_fields["bio"].type_str == "TextField"

    def test_raw_implicit_id_is_bigautofield(self, django_models_dir: Path):
        entities, _ = parse_models_directory(django_models_dir, django_raw_types=True)
        author_fields = {f.name: f for f in entities["Author"].fields}
        assert author_fields["id"].type_str == "BigAutoField"

    def test_db_table_override(self, django_models_dir: Path):
        entities, _ = parse_models_directory(django_models_dir)
        assert entities["Post"].table_name == "blog_post"

    def test_default_table_name_is_snake_case(self, django_models_dir: Path):
        entities, _ = parse_models_directory(django_models_dir)
        assert entities["Author"].table_name == "author"


class TestDjangoForeignKey:
    def test_foreign_key_is_modeled_as_id_column(self, django_models_dir: Path):
        entities, _ = parse_models_directory(django_models_dir)
        post_fields = {f.name: f for f in entities["Post"].fields}
        assert "author_id" in post_fields
        assert post_fields["author_id"].is_foreign_key is True
        assert post_fields["author_id"].foreign_table == "author.id"

    def test_foreign_key_renders_n_to_one(self, django_models_dir: Path):
        entities, enums = parse_models_directory(django_models_dir)
        output = PlantUMLGenerator(entities, enums).generate()
        assert 'Post }o--|| Author : "author_id"' in output

    def test_self_reference_foreign_key(self, django_models_dir: Path):
        entities, enums = parse_models_directory(django_models_dir)
        output = PlantUMLGenerator(entities, enums).generate()
        assert frozenset(("Category",)) in [frozenset(p) for p in _edges(output)] or any(
            "Category" in line and "--" in line for line in output.splitlines()
        )


class TestDjangoOneToOne:
    def test_one_to_one_renders_with_one_to_one_cardinality(self, django_models_dir: Path):
        entities, enums = parse_models_directory(django_models_dir)
        output = PlantUMLGenerator(entities, enums).generate()
        assert 'Profile ||--|| Author : "author"' in output


class TestDjangoManyToMany:
    def test_plain_m2m_renders_direct_m2m_edge(self, django_models_dir: Path):
        entities, enums = parse_models_directory(django_models_dir)
        output = PlantUMLGenerator(entities, enums).generate()
        assert 'Post }o--o{ Tag : "tags"' in output

    def test_through_model_is_a_regular_entity(self, django_models_dir: Path):
        entities, enums = parse_models_directory(django_models_dir)
        output = PlantUMLGenerator(entities, enums).generate()
        # Membership is drawn with FK edges to both endpoints.
        assert frozenset(("Membership", "Author")) in _edges(output)
        assert frozenset(("Membership", "Group")) in _edges(output)

    def test_m2m_through_has_no_spurious_direct_edge(self, django_models_dir: Path):
        entities, enums = parse_models_directory(django_models_dir)
        output = PlantUMLGenerator(entities, enums).generate()
        # The Group<->Author M:N goes through Membership, not as a direct edge.
        assert frozenset(("Group", "Author")) not in _edges(output)


class TestDjangoSourcesFilter:
    def test_django_can_be_selected_via_sources(self, django_models_dir: Path):
        entities, _ = parse_models_directory(django_models_dir, sources=["django"])
        assert "Author" in entities

    def test_excluding_django_yields_no_entities(self, django_models_dir: Path):
        entities, _ = parse_models_directory(django_models_dir, sources=["sqlmodel"])
        assert entities == {}
