"""Django multi-table inheritance (#233).

A model that subclasses a *concrete* model gets its own table holding only its
own fields plus a ``<parent>_ptr`` one-to-one link to the parent, which is the
child's primary key unless the child declares one. Abstract bases are still
copied into each subclass.
"""

from pathlib import Path

from erdify.config import EntityInfo, FieldInfo
from erdify.generator import generate_mermaid
from erdify.parser import parse_models_directory


def _parse(tmp_path: Path, body: str) -> dict[str, EntityInfo]:
    (tmp_path / "models.py").write_text(
        "from django.db import models\n\n\n" + body, encoding="utf-8"
    )
    entities, _ = parse_models_directory(tmp_path)
    return entities


def _cols(entity: EntityInfo) -> list[tuple[str, str, bool, bool, bool, str | None]]:
    """(name, type, pk, fk, unique, foreign_table) per field."""
    return [
        (f.name, f.type_str, f.is_primary_key, f.is_foreign_key, f.is_unique, f.foreign_table)
        for f in entity.fields
    ]


def _field(entity: EntityInfo, name: str) -> FieldInfo:
    return next(f for f in entity.fields if f.name == name)


ISSUE = """
class Parent(models.Model):
    code = models.CharField(max_length=5, primary_key=True)
    name = models.CharField(max_length=50)


class Child(Parent):
    extra = models.IntegerField()


class Order(models.Model):
    child = models.ForeignKey(Child, on_delete=models.CASCADE)
"""


class TestParentLink:
    def test_child_has_only_its_own_fields_and_the_ptr(self, tmp_path: Path):
        entities = _parse(tmp_path, ISSUE)
        assert _cols(entities["Child"]) == [
            ("parent_ptr_id", "str", True, True, False, "parent.code"),
            ("extra", "int", False, False, False, None),
        ]
        assert [f.name for f in entities["Parent"].fields] == ["code", "name"]

    def test_drawn_one_to_one_to_parent(self, tmp_path: Path):
        out = generate_mermaid(_parse(tmp_path, ISSUE))
        assert 'Child |o--|| Parent : "parent_ptr_id"' in out

    def test_foreign_key_to_child_references_the_ptr(self, tmp_path: Path):
        fk = _field(_parse(tmp_path, ISSUE)["Order"], "child_id")
        assert (fk.type_str, fk.foreign_table) == ("str", "child.parent_ptr_id")

    def test_implicit_parent_id(self, tmp_path: Path):
        entities = _parse(
            tmp_path,
            """
class Place(models.Model):
    name = models.CharField(max_length=50)


class Restaurant(Place):
    serves_pizza = models.BooleanField()
""",
        )
        assert _cols(entities["Restaurant"]) == [
            ("place_ptr_id", "int", True, True, False, "place.id"),
            ("serves_pizza", "bool", False, False, False, None),
        ]

    def test_ptr_name_is_lowercased_model_name(self, tmp_path: Path):
        entities = _parse(
            tmp_path,
            """
class OrderItem(models.Model):
    pass


class GiftItem(OrderItem):
    pass
""",
        )
        assert [f.name for f in entities["GiftItem"].fields] == ["orderitem_ptr_id"]

    def test_parent_db_table(self, tmp_path: Path):
        entities = _parse(
            tmp_path,
            """
class Place(models.Model):
    class Meta:
        db_table = "places"


class Restaurant(Place):
    pass
""",
        )
        assert _field(entities["Restaurant"], "place_ptr_id").foreign_table == "places.id"


class TestAbstractBases:
    SRC = """
class Stamped(models.Model):
    created = models.DateTimeField()

    class Meta:
        abstract = True


class Place(Stamped):
    name = models.CharField(max_length=50)


class Tagged(models.Model):
    tag = models.CharField(max_length=10)

    class Meta:
        abstract = True


class Restaurant(Tagged, Place):
    seats = models.IntegerField()
"""

    def test_abstract_base_of_child_is_copied(self, tmp_path: Path):
        entities = _parse(tmp_path, self.SRC)
        assert [f.name for f in entities["Restaurant"].fields] == ["place_ptr_id", "tag", "seats"]

    def test_abstract_base_of_parent_stays_in_parent(self, tmp_path: Path):
        entities = _parse(tmp_path, self.SRC)
        assert [f.name for f in entities["Place"].fields] == ["id", "created", "name"]


class TestRelationshipsStayOnParent:
    def test_parent_fk_and_m2m_not_copied(self, tmp_path: Path):
        entities = _parse(
            tmp_path,
            """
class Parent(models.Model):
    parent = models.ForeignKey("self", null=True, on_delete=models.CASCADE)
    peers = models.ManyToManyField("self")


class Child(Parent):
    extra = models.IntegerField()
""",
        )
        assert [f.name for f in entities["Child"].fields] == ["parent_ptr_id", "extra"]
        assert entities["Child"].relationships == []
        assert _field(entities["Parent"], "parent_id").foreign_table == "parent.id"


class TestExplicitKeys:
    def test_explicit_parent_link_replaces_ptr(self, tmp_path: Path):
        entities = _parse(
            tmp_path,
            """
class Place(models.Model):
    pass


class Restaurant(Place):
    place = models.OneToOneField(Place, on_delete=models.CASCADE, parent_link=True)
    seats = models.IntegerField()
""",
        )
        assert _cols(entities["Restaurant"]) == [
            ("place_id", "int", True, True, False, "place.id"),
            ("seats", "int", False, False, False, None),
        ]

    def test_child_primary_key_makes_ptr_a_unique_link(self, tmp_path: Path):
        entities = _parse(
            tmp_path,
            """
class Place(models.Model):
    pass


class Restaurant(Place):
    code = models.CharField(max_length=5, primary_key=True)
""",
        )
        assert _cols(entities["Restaurant"]) == [
            ("place_ptr_id", "int", False, True, True, "place.id"),
            ("code", "str", True, False, False, None),
        ]


class TestHierarchies:
    def test_chain_links_to_nearest_parent(self, tmp_path: Path):
        entities = _parse(
            tmp_path,
            """
class Place(models.Model):
    name = models.CharField(max_length=50)


class Restaurant(Place):
    seats = models.IntegerField()


class Pizzeria(Restaurant):
    oven = models.CharField(max_length=10)
""",
        )
        assert _cols(entities["Pizzeria"]) == [
            ("restaurant_ptr_id", "int", True, True, False, "restaurant.place_ptr_id"),
            ("oven", "str", False, False, False, None),
        ]

    def test_multiple_concrete_parents(self, tmp_path: Path):
        entities = _parse(
            tmp_path,
            """
class Place(models.Model):
    pass


class Business(models.Model):
    pass


class Shop(Place, Business):
    pass
""",
        )
        assert _cols(entities["Shop"]) == [
            ("place_ptr_id", "int", True, True, False, "place.id"),
            ("business_ptr_id", "int", False, True, True, "business.id"),
        ]


class TestProxyModels:
    def test_proxy_model_is_not_drawn(self, tmp_path: Path):
        entities = _parse(
            tmp_path,
            """
class Person(models.Model):
    name = models.CharField(max_length=50)


class OrderedPerson(Person):
    class Meta:
        proxy = True
""",
        )
        assert set(entities) == {"Person"}

    def test_subclass_of_proxy_links_to_the_concrete_model(self, tmp_path: Path):
        """Django links a subclass of a proxy to the model the proxy stands for."""
        entities = _parse(
            tmp_path,
            """
class Person(models.Model):
    name = models.CharField(max_length=50)


class OrderedPerson(Person):
    class Meta:
        proxy = True


class Employee(OrderedPerson):
    badge = models.IntegerField()
""",
        )
        assert set(entities) == {"Person", "Employee"}
        assert _cols(entities["Employee"]) == [
            ("person_ptr_id", "int", True, True, False, "person.id"),
            ("badge", "int", False, False, False, None),
        ]

    def test_proxy_without_concrete_model_links_nothing(self, tmp_path: Path):
        """A proxy whose concrete model was not scanned yields no link (no crash)."""
        entities = _parse(
            tmp_path,
            """
class Loop(models.Model):
    class Meta:
        proxy = True


class Leaf(Loop):
    pass
""",
        )
        assert _cols(entities["Leaf"]) == [("id", "int", True, False, False, None)]
