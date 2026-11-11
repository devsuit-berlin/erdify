"""What erdify knows about ``django.contrib`` models without reading Django.

Two things the scanned files can't show:

* The **abstract user bases** a custom user model builds on (``AbstractUser``,
  ``AbstractBaseUser``, ``PermissionsMixin``). Their definitions below mirror
  Django's (5.2 - 6.1, checked by the ground-truth tests) and are added as
  abstract classes when a scanned file imports them, so their fields are
  inherited like any other abstract base's (#277).
* The **tables of concrete contrib models** a relation can point at
  (``auth.User`` -> ``auth_user``), including ``settings.AUTH_USER_MODEL`` and
  ``get_user_model()`` (#278).

Contrib models themselves are not drawn: they are not part of the project.
"""

import ast
from typing import Dict, Iterable, Iterator, List, Set

#: Concrete contrib models a relation may target -> their table.
CONTRIB_TABLES: Dict[str, str] = {
    "auth.User": "auth_user",
    "auth.Group": "auth_group",
    "auth.Permission": "auth_permission",
    "contenttypes.ContentType": "django_content_type",
}

#: Modules that export contrib names -> the names erdify knows from them.
CONTRIB_MODULES: Dict[str, Set[str]] = {
    "django.contrib.auth.models": {
        "User",
        "Group",
        "Permission",
        "AbstractUser",
        "AbstractBaseUser",
        "PermissionsMixin",
    },
    "django.contrib.auth.base_user": {"AbstractBaseUser"},
    "django.contrib.contenttypes.models": {"ContentType"},
}

#: The user model Django uses when ``AUTH_USER_MODEL`` is not swapped.
DEFAULT_USER_MODEL = "auth.User"

#: The abstract user bases, as Django defines their fields.
ABSTRACT_USER_BASES = """
class AbstractBaseUser(models.Model):
    password = models.CharField(max_length=128)
    last_login = models.DateTimeField(blank=True, null=True)

    class Meta:
        abstract = True


class PermissionsMixin(models.Model):
    is_superuser = models.BooleanField(default=False)
    groups = models.ManyToManyField("auth.Group", blank=True)
    user_permissions = models.ManyToManyField("auth.Permission", blank=True)

    class Meta:
        abstract = True


class AbstractUser(AbstractBaseUser, PermissionsMixin):
    username = models.CharField(max_length=150, unique=True)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    email = models.EmailField(blank=True)
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    date_joined = models.DateTimeField()

    class Meta:
        abstract = True
"""

_QUALIFIED = {name.rpartition(".")[2]: name for name in CONTRIB_TABLES}


def imported_contrib_names(trees: Iterable[ast.Module]) -> Set[str]:
    """Contrib names imported (``from <contrib module> import X``) by any tree."""
    names: Set[str] = set()
    for tree in trees:
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in CONTRIB_MODULES:
                known = CONTRIB_MODULES[node.module]
                names.update(alias.name for alias in node.names if alias.name in known)
    return names


def contrib_bindings(tree: ast.Module) -> Dict[str, str]:
    """Local name -> qualified contrib model, as the module binds it at the end.

    ``from django.contrib.auth.models import Group as AuthGroup`` binds
    ``AuthGroup`` to ``"auth.Group"``. Only module-level statements count
    (also inside module-level ``if`` / ``try`` / ``with`` blocks, not in
    ``except`` handlers), in order, so
    an import inside a function is ignored and a later local ``class Group`` or
    other import of the name replaces the binding, as in Python.
    """
    bindings: Dict[str, str] = {}
    for node in _module_statements(tree.body):
        if isinstance(node, ast.ImportFrom):
            known = CONTRIB_MODULES.get(node.module or "", set())
            for alias in node.names:
                local = alias.asname or alias.name
                qualified = _QUALIFIED.get(alias.name)
                if qualified is not None and alias.name in known:
                    bindings[local] = qualified
                else:
                    bindings.pop(local, None)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                bindings.pop(alias.asname or alias.name.partition(".")[0], None)
        elif isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            bindings.pop(node.name, None)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                for name in ast.walk(target):
                    if isinstance(name, ast.Name):
                        bindings.pop(name.id, None)
    return bindings


def _module_statements(body: List[ast.stmt]) -> Iterator[ast.stmt]:
    """Module-level statements in order, entering ``if`` / ``try`` / ``with`` blocks.

    ``except`` handlers are skipped: a fallback there (``except ImportError:
    Group = None``) normally doesn't run.
    """
    for node in body:
        yield node
        if isinstance(node, (ast.If, ast.Try, ast.With)):
            for block in ("body", "orelse", "finalbody"):
                yield from _module_statements(getattr(node, block, []))


def abstract_user_bases(imported: Set[str], defined: Set[str]) -> Dict[str, ast.ClassDef]:
    """The abstract user bases to add: imported, not defined in the scanned files.

    ``AbstractUser`` brings the two bases it is built on.
    """
    wanted = imported & {"AbstractUser", "AbstractBaseUser", "PermissionsMixin"}
    if "AbstractUser" in wanted:
        wanted |= {"AbstractBaseUser", "PermissionsMixin"}
    classes = {
        node.name: node
        for node in ast.parse(ABSTRACT_USER_BASES).body
        if isinstance(node, ast.ClassDef)
    }
    return {name: node for name, node in classes.items() if name in wanted - defined}


def contrib_target(reference: str) -> str | None:
    """``"auth.User"`` / ``"auth.user"`` -> ``"auth.User"``; None if not a contrib model."""
    label, _, model = reference.rpartition(".")
    for qualified in CONTRIB_TABLES:
        q_label, _, q_model = qualified.partition(".")
        if label == q_label and model.lower() == q_model.lower():
            return qualified
    return None
