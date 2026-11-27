"""ConfigEntry-backed Area configuration used by the admin panel."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers.area_registry import async_get as async_get_area_registry

from custom_components.adaptive_areas.const import (
    CONF_EXCLUDE_ENTITIES,
    CONF_RETAINED_FEATURES,
    CONF_AREA_ILLUMINANCE_SENSOR,
    AREA_TYPE_META,
    CONF_AREAS,
    CONF_ENABLED_FEATURES,
    CONF_FEATURE_LIGHT_GROUPS,
    CONF_GLOBAL_ENTRY,
    CONF_GLOBAL_OPTIONS,
    CONF_FEATURE_LIST,
    CONF_FEATURE_LIST_GLOBAL,
    CONF_FEATURE_LIST_META,
    CONF_FEATURE_SWITCH_GROUPS,
    CONF_ID,
    CONF_NAME,
    CONF_PRESENCE_DEVICE_PLATFORMS,
    CONF_SECONDARY_STATES,
    ALL_PRESENCE_DEVICE_PLATFORMS,
    DEFAULT_PRESENCE_DEVICE_PLATFORMS,
    CONF_TYPE,
    DOMAIN,
    META_AREA_SCHEMA,
    REGULAR_AREA_SCHEMA,
)
from custom_components.adaptive_areas.helpers.light_ownership import GROUP_MEMBER_KEYS
from custom_components.adaptive_areas.helpers.light_ownership_runtime import (
    excluded_members_by_group,
    light_group_ownership_problem,
)
from custom_components.adaptive_areas.helpers.sources import is_illuminance_state
from custom_components.adaptive_areas.migration import get_global_entries


def _entry_options(entry: ConfigEntry) -> dict[str, Any]:
    """Return the persisted effective config without exposing mutable entry data."""
    return {**entry.data, **entry.options}


def get_global_options(entry: ConfigEntry) -> dict[str, Any]:
    """Return a detached, empty-safe view of GlobalEntry options."""
    options = entry.options.get(CONF_GLOBAL_OPTIONS, {})
    return dict(options) if isinstance(options, Mapping) else {}


def update_global_options(
    hass: HomeAssistant, entry: ConfigEntry, updates: Mapping[str, Any]
) -> None:
    """Persist a partial global-options update without touching Area settings."""
    options = {**get_global_options(entry), **updates}
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_GLOBAL_OPTIONS: options}
    )


def _schema_for(config: Mapping[str, Any]):
    """Select the existing ConfigFlow schema for the requested Area type."""
    return (
        META_AREA_SCHEMA
        if config.get(CONF_TYPE) == AREA_TYPE_META
        else REGULAR_AREA_SCHEMA
    )


def _available_features(config: Mapping[str, Any]) -> list[str]:
    """Mirror the ConfigFlow feature availability without runtime inference."""
    if config.get(CONF_TYPE) != AREA_TYPE_META:
        features = CONF_FEATURE_LIST
    elif str(config.get(CONF_ID, "")).lower() == "global":
        features = CONF_FEATURE_LIST_GLOBAL
    else:
        features = CONF_FEATURE_LIST_META
    return [feature for feature in features if feature != CONF_FEATURE_SWITCH_GROUPS]


def validate_area_options(
    current: Mapping[str, Any], updates: Mapping[str, Any]
) -> tuple[dict[str, Any] | None, dict[str, str]]:
    """Validate panel edits with the exact persisted Area schemas."""
    candidate = {**current, **updates}
    candidate[CONF_SECONDARY_STATES] = {
        **current.get(CONF_SECONDARY_STATES, {}),
        **updates.get(CONF_SECONDARY_STATES, {}),
    }
    if CONF_ENABLED_FEATURES in updates:
        candidate[CONF_ENABLED_FEATURES] = updates[CONF_ENABLED_FEATURES]
    try:
        return _schema_for(candidate)(candidate), {}
    except vol.MultipleInvalid as err:
        return None, {
            str(issue.path[0]) if issue.path else "base": issue.msg
            for issue in err.errors
        }


def area_configuration(
    entry: ConfigEntry, config: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Build the editable DTO from persisted settings, never runtime state."""
    config = dict(config) if config is not None else _entry_options(entry)
    validated, errors = validate_area_options(config, {})
    return {
        "entry_id": entry.entry_id,
        "area_id": str(config[CONF_ID]),
        "name": config[CONF_NAME],
        "type": config[CONF_TYPE],
        "options": validated if validated is not None else config,
        "available_features": _available_features(config),
        "validation_errors": errors,
    }


def area_configurations(entry: ConfigEntry) -> list[dict[str, Any]]:
    """Return every logical Area configuration owned by an entry."""
    areas = entry.options.get(CONF_AREAS, entry.data.get(CONF_AREAS))
    if entry.data.get(CONF_GLOBAL_ENTRY) and not isinstance(areas, dict):
        # A GlobalEntry without Areas owns no logical Area yet.
        return []
    if isinstance(areas, dict):
        return sorted(
            [
                area_configuration(entry, config)
                for config in areas.values()
                if isinstance(config, Mapping)
            ],
            key=lambda item: item["area_id"],
        )
    return [area_configuration(entry)]


def available_areas(hass: HomeAssistant) -> list[dict[str, str]]:
    """List unused Home Assistant Areas available for regular Adaptive Areas."""
    configured = set()
    for entry in hass.config_entries.async_entries(DOMAIN):
        areas = entry.options.get(CONF_AREAS, entry.data.get(CONF_AREAS))
        if isinstance(areas, dict):
            configured.update(str(area_id) for area_id in areas)
        elif entry.data.get(CONF_ID):
            configured.add(str(entry.data[CONF_ID]))
    return [
        {"id": area.id, "name": area.name}
        for area in sorted(
            async_get_area_registry(hass).async_list_areas(),
            key=lambda area: area.name.casefold(),
        )
        if area.id not in configured
    ]


async def async_create_area(
    hass: HomeAssistant, area_id: str, updates: Mapping[str, Any]
) -> tuple[ConfigEntry | None, dict[str, str]]:
    """Create one regular Area in the unique GlobalEntry container."""
    entries = get_global_entries(hass)
    if len(entries) != 1:
        return None, {"base": "Exactly one GlobalEntry is required"}
    entry = entries[0]
    area = async_get_area_registry(hass).async_get_area(area_id)
    if area is None:
        return None, {"area_id": "Unknown Home Assistant area"}
    areas = dict(entry.options.get(CONF_AREAS, entry.data.get(CONF_AREAS, {})))
    if area_id in areas:
        existing = areas[area_id]
        if isinstance(existing, Mapping) and existing.get(CONF_TYPE) == AREA_TYPE_META:
            # Areas and floors share one key space in the stored configuration; an
            # Area cannot use the ID of a configured floor or Meta Area (RC.4 decision).
            return None, {
                "area_id": "A floor or Meta Area with this ID is already configured"
            }
        return None, {"area_id": "Area is already configured"}
    if updates.get(CONF_TYPE) == AREA_TYPE_META:
        return None, {CONF_TYPE: "Home Assistant areas cannot be Meta Areas"}

    defaults, errors = validate_area_options({CONF_TYPE: "interior"}, updates)
    if defaults is None:
        return None, errors
    data = {**defaults, CONF_ID: area_id, CONF_NAME: area.name}
    areas[area_id] = data
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_AREAS: areas}
    )
    await hass.async_block_till_done()
    return entry, {}


def _new_unsupported_presence_platforms(
    current: Mapping[str, Any], updates: Mapping[str, Any]
) -> list[str]:
    """Return unsupported presence domains that this save would newly add.

    A value already stored stays accepted, so unchanged entries keep saving.
    A value the user removed is not in the stored state anymore and is rejected
    when it is selected again.
    """
    if CONF_PRESENCE_DEVICE_PLATFORMS not in updates:
        return []
    requested = updates[CONF_PRESENCE_DEVICE_PLATFORMS]
    if not isinstance(requested, list):
        requested = [requested] if requested is not None else []
    stored = set(
        current.get(CONF_PRESENCE_DEVICE_PLATFORMS, DEFAULT_PRESENCE_DEVICE_PLATFORMS)
        or []
    )
    return sorted(
        str(domain)
        for domain in set(requested)
        if domain not in ALL_PRESENCE_DEVICE_PLATFORMS and domain not in stored
    )


ILLUMINANCE_SENSOR_EXPECTED = "expected_illuminance_sensor"
ILLUMINANCE_SENSOR_UNKNOWN = "unknown_illuminance_sensor"
ILLUMINANCE_SENSOR_MESSAGES = {
    ILLUMINANCE_SENSOR_EXPECTED: "Expected an illuminance sensor",
    ILLUMINANCE_SENSOR_UNKNOWN: "Unknown illuminance sensor",
}


def illuminance_sensor_error(
    hass: HomeAssistant, value: Any, stored: Any = ""
) -> str | None:
    """Return an error code for a new Area brightness sensor, or None when it is valid.

    Only a changed value is checked: a stored sensor that is temporarily unavailable keeps
    the other settings savable. Empty means: use the global light sensor (valid).
    """
    if not value or value == stored:
        return None
    if not isinstance(value, str) or not value.startswith("sensor."):
        return ILLUMINANCE_SENSOR_EXPECTED
    state = hass.states.get(value)
    if state is None:
        return ILLUMINANCE_SENSOR_UNKNOWN
    if not is_illuminance_state(state):
        return ILLUMINANCE_SENSOR_EXPECTED
    return None


def _with_retained_features(
    current: Mapping[str, Any], updates: Mapping[str, Any]
) -> dict[str, Any]:
    """Park the configuration of disabled features and restore it on re-enabling.

    The enabled features keep their runtime meaning: a parked feature is inactive. A
    feature enabled again with an empty configuration gets its parked settings back; a
    submitted non-empty configuration replaces them. Nothing is deleted silently.
    """
    if CONF_ENABLED_FEATURES not in updates:
        return dict(updates)
    previous = current.get(CONF_ENABLED_FEATURES) or {}
    submitted = dict(updates[CONF_ENABLED_FEATURES] or {})
    retained = dict(current.get(CONF_RETAINED_FEATURES) or {})
    for key, config in previous.items():
        if key not in submitted:
            retained[key] = config
    for key in list(submitted):
        if submitted[key] in (None, {}) and key in retained:
            submitted[key] = retained.pop(key)
        else:
            retained.pop(key, None)
    return {
        **updates,
        CONF_ENABLED_FEATURES: submitted,
        CONF_RETAINED_FEATURES: retained,
    }


async def async_update_area(
    hass: HomeAssistant,
    area_id: str | ConfigEntry,
    updates: Mapping[str, Any],
    details: dict[str, dict[str, str]] | None = None,
) -> dict[str, str]:
    """Atomically update one logical Area and reload its container once.

    Errors map a field to an error key. For light ownership conflicts, `details` (when given)
    receives the placeholders of the message (lamp, owning group's Area) for that field.
    """
    legacy_entry = area_id if isinstance(area_id, ConfigEntry) else None
    if legacy_entry is not None:
        entry = legacy_entry
        current = _entry_options(entry)
    else:
        entries = get_global_entries(hass)
        if len(entries) != 1:
            return {"base": "Exactly one GlobalEntry is required"}
        entry = entries[0]
        areas = dict(entry.options.get(CONF_AREAS, entry.data.get(CONF_AREAS, {})))
        current = areas.get(area_id)
        if not isinstance(current, Mapping):
            return {"area_id": "Adaptive Area not found"}
        current = dict(current)
    if updates.get(CONF_TYPE, current[CONF_TYPE]) != current[CONF_TYPE] and (
        updates.get(CONF_TYPE, current[CONF_TYPE]) == AREA_TYPE_META
        or current[CONF_TYPE] == AREA_TYPE_META
    ):
        return {CONF_TYPE: "Area type cannot change to or from Meta"}
    unsupported = set(updates.get(CONF_ENABLED_FEATURES, {})) - set(
        _available_features(current)
    )
    if unsupported:
        return {CONF_ENABLED_FEATURES: "Unsupported feature selection"}
    updates = _with_retained_features(current, updates)
    if CONF_AREA_ILLUMINANCE_SENSOR in updates:
        code = illuminance_sensor_error(
            hass,
            updates[CONF_AREA_ILLUMINANCE_SENSOR],
            current.get(CONF_AREA_ILLUMINANCE_SENSOR, ""),
        )
        if code is not None:
            return {CONF_AREA_ILLUMINANCE_SENSOR: ILLUMINANCE_SENSOR_MESSAGES[code]}
    if new_domains := _new_unsupported_presence_platforms(current, updates):
        return {
            CONF_PRESENCE_DEVICE_PLATFORMS: "Unsupported presence domain: "
            + ", ".join(new_domains)
        }
    validated, errors = validate_area_options(current, updates)
    if validated is None:
        return errors
    # Identity belongs to the container key and is deliberately not panel-editable.
    validated.pop(CONF_ID, None)
    validated.pop(CONF_NAME, None)
    # Same ownership rule as the options flow: a light belongs to one individual group only,
    # within one Area and across all Areas. Checked only when the light groups are saved, so
    # unrelated edits never fail on a light that Home Assistant no longer knows.
    # Refused saves leave the stored config untouched.
    submitted = updates.get(CONF_ENABLED_FEATURES) or {}
    if CONF_FEATURE_LIGHT_GROUPS in submitted:
        # A configured group member (also a nested native group) must not switch an
        # excluded lamp through the group: refused at save, nothing is changed.
        configured_groups = (
            validated.get(CONF_ENABLED_FEATURES, {}).get(CONF_FEATURE_LIGHT_GROUPS)
            or {}
        )
        members = [
            str(item)
            for key in GROUP_MEMBER_KEYS
            for item in (configured_groups.get(key) or [])
        ]
        blocked = excluded_members_by_group(
            hass, members, validated.get(CONF_EXCLUDE_ENTITIES) or []
        )
        if blocked:
            member, hits = sorted(blocked.items())[0]
            return {
                CONF_ENABLED_FEATURES: (
                    f"Group member {member} would switch excluded lights: {', '.join(hits)}"
                )
            }
    if CONF_FEATURE_LIGHT_GROUPS in submitted:
        own_groups = (
            validated.get(CONF_ENABLED_FEATURES, {}).get(CONF_FEATURE_LIGHT_GROUPS)
            or {}
        )
        own_area_id = current.get(CONF_ID) or (
            area_id if isinstance(area_id, str) else entry.unique_id
        )
        problem = light_group_ownership_problem(
            hass, f"{entry.entry_id}/{own_area_id}", own_groups
        )
    else:
        problem = None
    if problem is not None:
        key, error, placeholders = problem
        if details is not None:
            details[key] = placeholders
        return {key: error}
    if legacy_entry is not None:
        hass.config_entries.async_update_entry(entry, options=validated)
    else:
        areas[area_id] = {
            **validated,
            CONF_ID: area_id,
            CONF_NAME: current[CONF_NAME],
        }
        hass.config_entries.async_update_entry(
            entry, options={**entry.options, CONF_AREAS: areas}
        )
    await hass.async_block_till_done()
    return {}


async def async_delete_area(hass: HomeAssistant, area_id: str) -> dict[str, str]:
    """Remove one logical Area while retaining the GlobalEntry.

    The update reloads the GlobalEntry once. Its setup removes the device and the
    generated entities of every Area that is no longer configured, identified by the
    stable Area ID (see `_remove_orphaned_area_devices`). Other Areas, physical devices
    and foreign entities are untouched. A failed unload or setup is reported, never
    treated as a completed deletion.
    """
    entries = get_global_entries(hass)
    if len(entries) != 1:
        return {"base": "Exactly one GlobalEntry is required"}
    entry = entries[0]
    areas = dict(entry.options.get(CONF_AREAS, entry.data.get(CONF_AREAS, {})))
    if area_id not in areas:
        return {"area_id": "Adaptive Area not found"}
    was_loaded = entry.state is ConfigEntryState.LOADED
    areas.pop(area_id)
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_AREAS: areas}
    )
    await hass.async_block_till_done()
    if was_loaded and entry.state is not ConfigEntryState.LOADED:
        return {"base": f"GlobalEntry reload failed ({entry.state.value})"}
    return {}
