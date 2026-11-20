"""The enums erdify draws and the entities that use them (#369).

:func:`enum_users` is the one rule for which enums a diagram includes: an
enum is drawn when a field's type names it. The PlantUML and Mermaid
generators use it, and ``--format json`` gives each enum's entities from it
(``used_by``), so a tool built on erdify gets exactly the enums erdify draws,
and which entities use each one.
"""

from typing import Dict, List, Mapping

from .config import EntityInfo, EnumInfo


def enum_users(
    entities: Mapping[str, EntityInfo],
    enums: Mapping[str, EnumInfo] | None,
    *,
    include_enums: bool = True,
) -> Dict[str, List[str]]:
    """The enums erdify draws, each with the entities that have a field of it.

    A field uses an enum when the last dotted part of its type
    (:attr:`FieldInfo.type_str`, e.g. ``Status`` or ``models.Status``) is a
    key of ``enums``. An enum no field uses is not drawn and is left out.

    Args:
        entities: Parsed entities, keyed as :func:`parse_models_directory`
            returns them.
        enums: Parsed enums, keyed likewise; ``None`` is no enums.
        include_enums: ``False`` gives an empty result, like
            ``--no-enums`` / ``include_enums=False`` for the diagrams (pass
            ``not project.settings.no_enums``).

    Returns:
        Enum key -> the names (:attr:`EntityInfo.name`, as in
        :func:`diagram_edges` endpoints) of the entities using it, each once,
        in entity order. Enum keys are sorted, the order the diagrams draw
        the enums in.
    """
    if not include_enums or not enums:
        return {}
    users: Dict[str, List[str]] = {}
    for entity in entities.values():
        for field in entity.fields:
            key = field.type_str.split(".")[-1]
            if key in enums:
                names = users.setdefault(key, [])
                if entity.name not in names:
                    names.append(entity.name)
    return {key: users[key] for key in sorted(users)}
