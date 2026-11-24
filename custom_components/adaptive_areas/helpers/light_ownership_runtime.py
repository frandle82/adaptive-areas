"""Runtime enforcement of light ownership for stored configurations.

Product rule: a physical light is an automatically controlled member of at most one Area.
The options flow refuses new conflicts. A configuration stored before that rule can still
contain one, so the automatic paths ask this module on every command:

- Policy targets never contain a conflicted light.
- A light group with a conflicted member is suppressed as one unit. It is never split into
  its physical members, and no replacement call goes to its other members.

The conflicts are computed from the current config entries and light states each time, so
a reload keeps the block and a corrected configuration lifts it without any repair step.
Nothing is changed in storage and no Area is preferred.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping

from homeassistant.core import HomeAssistant

from custom_components.adaptive_areas.const import (
    CONF_AREAS,
    CONF_ENABLED_FEATURES,
    CONF_FEATURE_LIGHT_GROUPS,
    CONF_ID,
    DOMAIN,
)
from homeassistant.helpers.area_registry import async_get as areareg_async_get
from homeassistant.helpers.entity_registry import async_get as entityreg_async_get

from custom_components.adaptive_areas.helpers.light_ownership import (
    GROUP_MEMBER_KEYS,
    OwnershipConflict,
    describe,
    expand_members,
    find_ownership_conflicts,
    group_units,
    ownership_conflict_error,
    resolve_group_tree,
)
from custom_components.adaptive_areas.migration import is_global_entry

_LOGGER = logging.getLogger(__name__)
_REPORTED: set[str] = set()


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return list(value)


def _light_groups_of(config: Mapping) -> dict:
    features = config.get(CONF_ENABLED_FEATURES) or {}
    return features.get(CONF_FEATURE_LIGHT_GROUPS) or {}


def light_group_configs_of_entry(entry) -> dict[str, dict]:
    """Light group configuration per Area key ("<entry_id>/<area_id>") of one entry.

    The GlobalEntry stores its Areas in the same CONF_AREAS mapping, so its Areas are
    included: otherwise a conflict between two stored Areas would never be seen.
    """
    areas = entry.options.get(CONF_AREAS, entry.data.get(CONF_AREAS))
    if isinstance(areas, dict):
        return {
            f"{entry.entry_id}/{area_id}": _light_groups_of(config)
            for area_id, config in areas.items()
            if isinstance(config, dict)
        }
    if is_global_entry(entry):
        return {}
    area_id = entry.data.get(CONF_ID) or entry.unique_id
    if not area_id:
        return {}
    return {
        f"{entry.entry_id}/{area_id}": _light_groups_of(entry.options)
        or _light_groups_of(entry.data)
    }


def _owner_details(hass, light, key, areas, members, own_key):
    """Owning group key and placeholders: the first other (Area, group) that reaches the lamp.

    The message names the group that already holds the lamp, not the one being saved.
    """
    area_registry = areareg_async_get(hass)
    for area_key, groups in areas.items():
        for group_key in GROUP_MEMBER_KEYS:
            if (area_key, group_key) == (own_key, key):
                continue
            for item in _as_list(groups.get(group_key)):
                item = str(item)
                if light == item or light in members.get(item, []):
                    area_id = area_key.split("/", 1)[-1]
                    area = area_registry.async_get_area(area_id)
                    return group_key, {
                        "light": light,
                        "area": area.name if area else area_id,
                    }
    return key, {"light": light, "area": ""}


def light_group_ownership_problem(
    hass: HomeAssistant, own_key: str, own_groups: Mapping
) -> tuple[str, str, dict[str, str]] | None:
    """Return (field key, error key, placeholders) if saving own_groups breaks ownership.

    Checks every stored Area of every Config Entry (GlobalEntry included); own_key's stored
    groups are replaced by own_groups. A group that cannot be resolved is an error, never
    conflict-free. Nothing is stored here; the caller refuses the save.
    """
    areas: dict[str, dict] = {}
    for entry in hass.config_entries.async_entries(DOMAIN):
        for area_key, groups in light_group_configs_of_entry(entry).items():
            if area_key != own_key:
                areas[area_key] = groups
    areas[own_key] = {
        key: own_groups[key] for key in GROUP_MEMBER_KEYS if key in own_groups
    }

    listed = [
        str(item)
        for groups in areas.values()
        for key in GROUP_MEMBER_KEYS
        for item in _as_list(groups.get(key))
    ]
    entity_registry = entityreg_async_get(hass)
    members, unresolved, unknown = resolve_group_tree(
        listed,
        _attributes_lookup(hass),
        lambda entity_id: entity_registry.async_get(entity_id) is not None,
    )
    fallback = next(
        (key for key in GROUP_MEMBER_KEYS if key in own_groups), GROUP_MEMBER_KEYS[0]
    )
    conflicts = find_ownership_conflicts(group_units(areas), members)
    if conflicts:
        light = conflicts[0].light
        key = next(
            (
                k
                for k in GROUP_MEMBER_KEYS
                if light in _as_list(own_groups.get(k))
                or light in members.get(light, [])
            ),
            fallback,
        )
        owner, details = _owner_details(hass, light, key, areas, members, own_key)
        return key, ownership_conflict_error(owner), details
    if unknown:
        return fallback, "light_entity_unknown", {"light": str(unknown[0]), "area": ""}
    if unresolved:
        return (
            fallback,
            "light_group_unresolved",
            {"light": str(unresolved[0]), "area": ""},
        )
    return None


def _attributes_lookup(hass: HomeAssistant):
    def attributes_of(entity_id: str):
        state = hass.states.get(entity_id)
        return None if state is None else state.attributes

    return attributes_of


def runtime_ownership_conflicts(hass: HomeAssistant) -> list[OwnershipConflict]:
    """Every physical light that is an automatic member of more than one Area now."""
    areas: dict[str, dict] = {}
    for entry in hass.config_entries.async_entries(DOMAIN):
        areas.update(light_group_configs_of_entry(entry))
    listed = sorted(
        {
            str(item)
            for groups in areas.values()
            for key in GROUP_MEMBER_KEYS
            for item in _as_list(groups.get(key))
        }
    )
    members, _unresolved, _unknown = resolve_group_tree(
        listed, _attributes_lookup(hass), lambda _entity_id: False
    )
    return find_ownership_conflicts(group_units(areas), members)


def conflicted_lights(hass: HomeAssistant) -> frozenset[str]:
    """Physical lights with a runtime ownership conflict. Each conflict is logged once."""
    conflicts = runtime_ownership_conflicts(hass)
    for line in describe(conflicts):
        if line not in _REPORTED:
            _REPORTED.add(line)
            _LOGGER.warning(
                "Light ownership conflict, automatic control blocked: %s", line
            )
    return frozenset(conflict.light for conflict in conflicts)


def group_is_blocked(
    hass: HomeAssistant,
    group_entity_id: str,
    configured: Iterable[str],
) -> bool:
    """Return whether the light group has at least one conflicted member.

    A conflicted group is one indivisible unit: the whole automatic group action is
    suppressed, never split into its physical members.
    """
    conflicted = conflicted_lights(hass)
    if not conflicted:
        return False
    members, _unresolved, _unknown = resolve_group_tree(
        [group_entity_id], _attributes_lookup(hass), lambda _entity_id: False
    )
    # An unresolved group has no known physical members; only its configured members count.
    physical = (
        expand_members([group_entity_id], members)
        if group_entity_id in members
        else frozenset()
    )
    return bool(conflicted & (physical | set(configured)))
