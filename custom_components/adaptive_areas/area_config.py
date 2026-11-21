"""ConfigEntry-backed Area configuration used by the admin panel."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.area_registry import async_get as async_get_area_registry

from custom_components.adaptive_areas.const import (
    AREA_TYPE_META,
    CONF_AREAS,
    CONF_ENABLED_FEATURES,
    CONF_GLOBAL_ENTRY,
    CONF_GLOBAL_OPTIONS,
    CONF_FEATURE_LIST,
    CONF_FEATURE_LIST_GLOBAL,
    CONF_FEATURE_LIST_META,
    CONF_FEATURE_SWITCH_GROUPS,
    CONF_ID,
    CONF_NAME,
    CONF_SECONDARY_STATES,
    CONF_TYPE,
    DOMAIN,
    META_AREA_SCHEMA,
    REGULAR_AREA_SCHEMA,
)
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


async def async_update_area(
    hass: HomeAssistant, area_id: str | ConfigEntry, updates: Mapping[str, Any]
) -> dict[str, str]:
    """Atomically update one logical Area and reload its container once."""
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
    validated, errors = validate_area_options(current, updates)
    if validated is None:
        return errors
    # Identity belongs to the container key and is deliberately not panel-editable.
    validated.pop(CONF_ID, None)
    validated.pop(CONF_NAME, None)
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
    """Remove one logical Area while retaining the GlobalEntry."""
    entries = get_global_entries(hass)
    if len(entries) != 1:
        return {"base": "Exactly one GlobalEntry is required"}
    entry = entries[0]
    areas = dict(entry.options.get(CONF_AREAS, entry.data.get(CONF_AREAS, {})))
    if area_id not in areas:
        return {"area_id": "Adaptive Area not found"}
    areas.pop(area_id)
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_AREAS: areas}
    )
    await hass.async_block_till_done()
    return {}
