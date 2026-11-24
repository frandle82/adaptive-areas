"""Unique light ownership: a physical light is a controllable group member of one Area only.

Three layers are kept apart and must never be treated as identical:

1. Home Assistant area: the registry area of an entity or device (informational here).
2. `include_entities`: entities an Area takes into its scope. Being in scope is not
   being a controllable group member.
3. Automatic light group membership: `overhead_lights`, `sleep_lights`, `accent_lights`,
   `task_lights`. A group entity (`light.group`) is resolved to its physical members.

The check compares physical light entity ids (group entities are expanded, never compared
as targets). It is pure: it reads a configuration snapshot and changes nothing.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

from custom_components.adaptive_areas.const import (
    CONF_ACCENT_LIGHTS,
    CONF_OVERHEAD_LIGHTS,
    CONF_SLEEP_LIGHTS,
    CONF_TASK_LIGHTS,
)

GROUP_MEMBER_KEYS = (
    CONF_OVERHEAD_LIGHTS,
    CONF_SLEEP_LIGHTS,
    CONF_ACCENT_LIGHTS,
    CONF_TASK_LIGHTS,
)
LIGHT_PREFIX = "light."


@dataclass(frozen=True, slots=True)
class OwnershipConflict:
    """One physical light that is a controllable group member of several Areas."""

    light: str
    areas: tuple[str, ...]
    reason: str = "multiple_areas_controllable"


MAX_GROUP_NODES = 500
MAX_GROUP_DEPTH = 16


def expand_members(
    entity_ids: Iterable[str],
    group_members: Mapping[str, Iterable[str]],
) -> frozenset[str]:
    """Resolve light groups to physical light members, nested groups included.

    `group_members` maps a light group entity id to its direct members. Cycles are cut by
    a visited set; recursion depth is capped at MAX_GROUP_DEPTH. A light that is not a
    known group is a physical light. Non-light entries are ignored.
    """
    resolved: set[str] = set()
    visited: set[str] = set()

    def walk(entity_id: str, depth: int) -> None:
        if not entity_id.startswith(LIGHT_PREFIX) or entity_id in visited:
            return
        visited.add(entity_id)
        members = group_members.get(entity_id)
        if members is None or depth >= MAX_GROUP_DEPTH:
            resolved.add(entity_id)
            return
        for member in members:
            walk(member, depth + 1)

    for entity_id in entity_ids:
        walk(entity_id, 0)
    return frozenset(resolved)


def controllable_members(
    area_config: Mapping[str, object],
    group_members: Mapping[str, Iterable[str]],
) -> frozenset[str]:
    """Physical lights that an Area controls as automatic group members."""
    listed: list[str] = []
    for key in GROUP_MEMBER_KEYS:
        value = area_config.get(key) or []
        if isinstance(value, str):
            value = [value]
        listed.extend(str(item) for item in value)
    return expand_members(listed, group_members)


def group_units(
    areas: Mapping[str, Mapping[str, object]],
) -> dict[str, dict[str, object]]:
    """Split every Area configuration into its individual light groups.

    The unit of ownership is one individually configured light group (overhead, sleep, accent,
    task). A physical light may belong to one such group only, within an Area and across
    Areas. Keys are "<area key>#<group key>"; the ALL group is never a unit (it is derived).
    """
    units: dict[str, dict[str, object]] = {}
    for area_key, config in areas.items():
        for key in GROUP_MEMBER_KEYS:
            if key in config:
                units[f"{area_key}#{key}"] = {key: config.get(key)}
    return units


def find_ownership_conflicts(
    areas: Mapping[str, Mapping[str, object]],
    group_members: Mapping[str, Iterable[str]] | None = None,
) -> list[OwnershipConflict]:
    """Return every physical light that is a controllable member of more than one Area.

    `areas` maps an Area key (for example "<entry_id>/<area_id>") to its configuration
    snapshot. Keys are compared as given; the result is sorted and deterministic.
    """
    members = group_members or {}
    owners: dict[str, list[str]] = {}
    for area_key in sorted(areas):
        for light in controllable_members(areas[area_key], members):
            owners.setdefault(light, []).append(area_key)
    return [
        OwnershipConflict(light=light, areas=tuple(sorted(keys)))
        for light, keys in sorted(owners.items())
        if len(keys) > 1
    ]


def describe(conflicts: Iterable[OwnershipConflict]) -> list[str]:
    """Human-readable diagnosis lines (no personal data, entity and area ids only)."""
    return [
        f"{c.light} is a controllable group member of {', '.join(c.areas)}; "
        "a light may belong to one Area only."
        for c in conflicts
    ]


def ownership_conflict_error(owner_group: str) -> str:
    """Error key for a conflict, named after the individual group that already holds the lamp.

    The translated message names the group (e.g. "Schlaflichter") directly, so no English
    internal key ever reaches a user-facing text.
    """
    return f"light_ownership_conflict_{owner_group.removesuffix('_lights')}"


OWNERSHIP_CONFLICT_ERRORS = frozenset(
    ownership_conflict_error(key) for key in GROUP_MEMBER_KEYS
)

LIGHT_OWNERSHIP_ERRORS = OWNERSHIP_CONFLICT_ERRORS | frozenset(
    {"light_group_unresolved", "light_entity_unknown"}
)


def resolve_group_tree(
    entity_ids: Iterable[str],
    attributes_of: Callable[[str], Mapping[str, object] | None],
    is_registry_known: Callable[[str], bool],
) -> tuple[dict[str, list[str]], list[str], list[str]]:
    """Walk light groups breadth-first from the given ids, nested groups included.

    Returns (members per reached group, unresolved group members, unknown entity ids).
    - A light state without `entity_id` is a physical light (any state, also unavailable or
      unknown: a known physical light is not a reason to refuse saving).
    - A light state with `entity_id` is a group; its members are walked.
    - No state but known in the registry: unresolved (cannot tell what it contains).
    - No state and not in the registry: unknown entity.
    The walk is bounded by MAX_GROUP_NODES and cycle-safe. A hit on the bound is reported
    as unresolved, never as conflict-free.
    """
    members: dict[str, list[str]] = {}
    unresolved: set[str] = set()
    unknown: set[str] = set()
    queue = deque(sorted({e for e in entity_ids if e.startswith(LIGHT_PREFIX)}))
    seen: set[str] = set()
    while queue:
        if len(seen) >= MAX_GROUP_NODES:
            unresolved.update(queue)
            break
        entity_id = queue.popleft()
        if entity_id in seen:
            continue
        seen.add(entity_id)
        attributes = attributes_of(entity_id)
        if attributes is None:
            (unresolved if is_registry_known(entity_id) else unknown).add(entity_id)
            continue
        if "entity_id" in attributes:
            listed = attributes.get("entity_id") or []
            if isinstance(listed, str):
                listed = [listed]
            direct = [
                str(item) for item in listed if str(item).startswith(LIGHT_PREFIX)
            ]
            members[entity_id] = direct
            queue.extend(direct)
    return members, sorted(unresolved), sorted(unknown)
