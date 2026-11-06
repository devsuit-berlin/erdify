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
    seats = models.IntegerField()
    place = models.OneToOneField(Place, on_delete=models.CASCADE, parent_link=True)
""",
        )
        # Declared after `seats`, the promoted link is still listed first.
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
        # The declared primary key is listed first.
        assert _cols(entities["Restaurant"]) == [
            ("code", "str", True, False, False, None),
            ("place_ptr_id", "int", False, True, True, "place.id"),
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
    place_no = models.AutoField(primary_key=True)


class Business(models.Model):
    business_no = models.AutoField(primary_key=True)


class Shop(Place, Business):
    pass
""",
        )
        assert _cols(entities["Shop"]) == [
            ("place_ptr_id", "int", True, True, False, "place.place_no"),
            ("business_ptr_id", "int", False, True, True, "business.business_no"),
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


class TestProxyTargets:
    """A relation to a proxy targets the concrete model it stands for."""

    SRC = """
class Person(models.Model):
    uid = models.UUIDField(primary_key=True)


class OrderedPerson(Person):
    class Meta:
        proxy = True


class SortedPerson(OrderedPerson):
    class Meta:
        proxy = True


class Note(models.Model):
    who = models.ForeignKey(OrderedPerson, on_delete=models.CASCADE)
    by = models.ForeignKey("SortedPerson", on_delete=models.CASCADE)
    readers = models.ManyToManyField(OrderedPerson)
"""

    def test_foreign_keys_reference_the_concrete_model(self, tmp_path: Path):
        note = _parse(tmp_path, self.SRC)["Note"]
        assert (_field(note, "who_id").foreign_table, _field(note, "who_id").type_str) == (
            "person.uid",
            "UUID",
        )
        assert _field(note, "by_id").foreign_table == "person.uid"

    def test_many_to_many_targets_the_concrete_model(self, tmp_path: Path):
        note = _parse(tmp_path, self.SRC)["Note"]
        assert note.relationships == [("Person", "many_to_many", "readers")]

    def test_edges_are_drawn(self, tmp_path: Path):
        out = generate_mermaid(_parse(tmp_path, self.SRC))
        assert 'Note }o--|| Person : "who_id"' in out
        assert 'Note }o--|| Person : "by_id"' in out


class TestToFieldOnInheritedColumns:
    SRC = """
class Place(models.Model):
    slug = models.SlugField(unique=True)


class Restaurant(Place):
    seats = models.IntegerField()


class Ref(models.Model):
    by_slug = models.ForeignKey(Restaurant, on_delete=models.CASCADE, to_field="slug")
    by_ptr = models.ForeignKey(Restaurant, on_delete=models.CASCADE, to_field="place_ptr")
    by_ptr_id = models.ForeignKey(Restaurant, on_delete=models.CASCADE, to_field="place_ptr_id")
    by_own = models.ForeignKey(Restaurant, on_delete=models.CASCADE, to_field="seats")
"""

    def test_parent_column_is_referenced_in_the_parent_table(self, tmp_path: Path):
        fk = _field(_parse(tmp_path, self.SRC)["Ref"], "by_slug_id")
        assert (fk.foreign_table, fk.type_str) == ("place.slug", "str")

    def test_implicit_link_as_to_field(self, tmp_path: Path):
        ref = _parse(tmp_path, self.SRC)["Ref"]
        for name in ("by_ptr_id", "by_ptr_id_id"):
            fk = _field(ref, name)
            assert (fk.foreign_table, fk.type_str) == ("restaurant.place_ptr_id", "int")

    def test_own_column(self, tmp_path: Path):
        fk = _field(_parse(tmp_path, self.SRC)["Ref"], "by_own_id")
        assert (fk.foreign_table, fk.type_str) == ("restaurant.seats", "int")


class TestAbstractLinks:
    def test_explicit_link_on_abstract_base(self, tmp_path: Path):
        entities = _parse(
            tmp_path,
            """
class Place(models.Model):
    pass


class LinkBase(models.Model):
    place = models.OneToOneField(Place, on_delete=models.CASCADE, parent_link=True)

    class Meta:
        abstract = True


class Restaurant(LinkBase, Place):
    seats = models.IntegerField()
""",
        )
        assert _cols(entities["Restaurant"]) == [
            ("place_id", "int", True, True, False, "place.id"),
            ("seats", "int", False, False, False, None),
        ]

    def test_explicit_link_with_primary_key(self, tmp_path: Path):
        entities = _parse(
            tmp_path,
            """
class Place(models.Model):
    pass


class Restaurant(Place):
    place = models.OneToOneField(
        Place, on_delete=models.CASCADE, parent_link=True, primary_key=True
    )
""",
        )
        assert _cols(entities["Restaurant"]) == [("place_id", "int", True, True, False, "place.id")]

    def test_abstract_base_of_a_concrete_model_passes_its_link_on(self, tmp_path: Path):
        """Django gives an abstract subclass of a concrete model its parent link."""
        entities = _parse(
            tmp_path,
            """
class Place(models.Model):
    name = models.CharField(max_length=50)


class Venue(Place):
    capacity = models.IntegerField()

    class Meta:
        abstract = True


class Stadium(Venue):
    roof = models.BooleanField()
""",
        )
        assert _cols(entities["Stadium"]) == [
            ("place_ptr_id", "int", True, True, False, "place.id"),
            ("capacity", "int", False, False, False, None),
            ("roof", "bool", False, False, False, None),
        ]


class TestInheritedKeys:
    def test_to_field_id_references_the_parent(self, tmp_path: Path):
        """A child has no `id` of its own: `to_field="id"` is the parent's implicit key."""
        entities = _parse(
            tmp_path,
            """
class Parent(models.Model):
    pass


class Child(Parent):
    pass


class Ref(models.Model):
    child = models.ForeignKey(Child, on_delete=models.CASCADE, to_field="id")
    parent = models.ForeignKey(Parent, on_delete=models.CASCADE, to_field="id")
""",
        )
        assert _field(entities["Ref"], "child_id").foreign_table == "parent.id"
        assert _field(entities["Ref"], "parent_id").foreign_table == "parent.id"

    def test_chained_inherited_to_field_keeps_its_type(self, tmp_path: Path):
        entities = _parse(
            tmp_path,
            """
class Parent(models.Model):
    slug = models.SlugField(unique=True)


class Child(Parent):
    pass


class Bridge(models.Model):
    child = models.OneToOneField(
        Child, on_delete=models.CASCADE, to_field="slug", primary_key=True
    )


class Ref(models.Model):
    bridge = models.ForeignKey(Bridge, on_delete=models.CASCADE)
""",
        )
        bridge = _field(entities["Bridge"], "child_id")
        assert (bridge.foreign_table, bridge.type_str) == ("parent.slug", "str")
        ref = _field(entities["Ref"], "bridge_id")
        assert (ref.foreign_table, ref.type_str) == ("bridge.child_id", "str")

    def test_removed_inherited_primary_key_restores_implicit_id(self, tmp_path: Path):
        entities = _parse(
            tmp_path,
            """
class Tokened(models.Model):
    token = models.UUIDField(primary_key=True)

    class Meta:
        abstract = True


class Parent(Tokened):
    token = None


class Child(Parent):
    pass


class Ref(models.Model):
    child = models.ForeignKey(Child, on_delete=models.CASCADE, to_field="id")
""",
        )
        assert [f.name for f in entities["Parent"].fields] == ["id"]
        assert _field(entities["Ref"], "child_id").foreign_table == "parent.id"


def test_shared_abstract_ancestors_are_walked_once(tmp_path: Path):
    """Stacked diamonds of abstract bases stay fast (memoized walk)."""
    layers = ["class L0(models.Model):\n    class Meta:\n        abstract = True\n"]
    for i in range(1, 30):
        layers.append(
            f"class A{i}(L{i - 1}):\n    class Meta:\n        abstract = True\n\n\n"
            f"class B{i}(L{i - 1}):\n    class Meta:\n        abstract = True\n\n\n"
            f"class L{i}(A{i}, B{i}):\n    class Meta:\n        abstract = True\n"
        )
    layers.append("class Leaf(L29):\n    pass\n")
    entities = _parse(tmp_path, "\n\n".join(layers))
    assert [f.name for f in entities["Leaf"].fields] == ["id"]


def test_concrete_parent_under_shared_abstract_ancestors(tmp_path: Path):
    """Stacked abstract diamonds over a concrete model yield one link, quickly."""
    layers = [
        "class Root(models.Model):\n    pass\n",
        "class L0(Root):\n    class Meta:\n        abstract = True\n",
    ]
    for i in range(1, 30):
        layers.append(
            f"class A{i}(L{i - 1}):\n    class Meta:\n        abstract = True\n\n\n"
            f"class B{i}(L{i - 1}):\n    class Meta:\n        abstract = True\n\n\n"
            f"class L{i}(A{i}, B{i}):\n    class Meta:\n        abstract = True\n"
        )
    layers.append("class Leaf(L29):\n    pass\n")
    entities = _parse(tmp_path, "\n\n".join(layers))
    assert [f.name for f in entities["Leaf"].fields] == ["root_ptr_id"]
