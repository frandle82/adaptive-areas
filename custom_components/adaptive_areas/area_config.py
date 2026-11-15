"""ConfigEntry-backed Area configuration used by the admin panel."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.area_registry import async_get as async_get_area_registry

from custom_components.adaptive_areas.const import (
    AdaptiveConfigEntryVersion,
    AREA_TYPE_META,
    CONF_ENABLED_FEATURES,
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


def _entry_options(entry: ConfigEntry) -> dict[str, Any]:
    """Return the persisted effective config without exposing mutable entry data."""
    return {**entry.data, **entry.options}


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


def area_configuration(entry: ConfigEntry) -> dict[str, Any]:
    """Build the editable DTO from persisted settings, never runtime state."""
    config = _entry_options(entry)
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


def available_areas(hass: HomeAssistant) -> list[dict[str, str]]:
    """List unused Home Assistant Areas available for regular Adaptive Areas."""
    configured = {
        str(entry.data.get(CONF_ID))
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.data.get(CONF_ID)
    }
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
    """Create one regular Area ConfigEntry from the standard defaults."""
    area = async_get_area_registry(hass).async_get_area(area_id)
    if area is None:
        return None, {"area_id": "Unknown Home Assistant area"}
    if any(
        str(entry.data.get(CONF_ID)) == area_id
        for entry in hass.config_entries.async_entries(DOMAIN)
    ):
        return None, {"area_id": "Area is already configured"}
    if updates.get(CONF_TYPE) == AREA_TYPE_META:
        return None, {CONF_TYPE: "Home Assistant areas cannot be Meta Areas"}

    defaults, errors = validate_area_options({CONF_TYPE: "interior"}, updates)
    if defaults is None:
        return None, errors
    data = {**defaults, CONF_ID: area_id, CONF_NAME: area.name}
    entry = ConfigEntry(
        data=data,
        discovery_keys=MappingProxyType({}),
        domain=DOMAIN,
        minor_version=AdaptiveConfigEntryVersion.MINOR,
        options={},
        source="user",
        subentries_data=None,
        title=area.name,
        unique_id=area_id,
        version=AdaptiveConfigEntryVersion.MAJOR,
    )
    await hass.config_entries.async_add(entry)
    return entry, {}


async def async_update_area(
    hass: HomeAssistant, entry: ConfigEntry, updates: Mapping[str, Any]
) -> dict[str, str]:
    """Atomically update one entry's panel-managed options and reload once."""
    current = _entry_options(entry)
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
    # Identity belongs to the entry data and is deliberately not panel-editable.
    validated.pop(CONF_ID, None)
    validated.pop(CONF_NAME, None)
    hass.config_entries.async_update_entry(entry, options=validated)
    await hass.async_block_till_done()
    return {}
