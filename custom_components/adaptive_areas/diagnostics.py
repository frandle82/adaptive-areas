"""Native Home Assistant diagnostics for Adaptive Areas."""

from collections import Counter
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from homeassistant.loader import async_get_integration

from custom_components.adaptive_areas.base.adaptive import (
    AdaptiveArea,
    AdaptiveMetaArea,
)
from custom_components.adaptive_areas.const import (
    AREA_STATE_CLEAR,
    AREA_STATE_OCCUPIED,
    CONF_CLEAR_TIMEOUT,
    CONF_ENABLED_FEATURES,
    CONF_ID,
    CONF_INCLUDE_ENTITIES,
    CONF_KEEP_ONLY_ENTITIES,
    CONF_PRESENCE_CONTROL_ENTITIES,
    CONF_SECONDARY_STATES,
    CONFIGURABLE_AREA_STATE_MAP,
    DATA_AREA_OBJECT,
    DEFAULT_CLEAR_TIMEOUT,
    DOMAIN,
    MODULE_DATA,
    MetaAreaType,
)
from custom_components.adaptive_areas.helpers.diagnostics import (
    safe_entity_descriptor,
)
from custom_components.adaptive_areas.repairs import (
    active_issue_count,
    get_repair_summary,
)


def _enabled_features(area: AdaptiveArea) -> list[str]:
    """Return stable enabled feature IDs for legacy and current configs."""
    features = area.config.get(CONF_ENABLED_FEATURES, {})
    if isinstance(features, dict):
        return sorted(str(feature) for feature in features)
    if isinstance(features, list):
        return sorted(str(feature) for feature in features)
    return []


def _meta_type(area: AdaptiveArea) -> str | None:
    """Return a non-identifying meta classification."""
    if not area.is_meta():
        return None
    if area.floor_id:
        return MetaAreaType.FLOOR
    if area.id in {
        MetaAreaType.GLOBAL,
        MetaAreaType.INTERIOR,
        MetaAreaType.EXTERIOR,
    }:
        return str(area.id)
    return "meta"


def _generated_entity_summary(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> dict[str, Any]:
    """Summarize generated entities without exporting identifiers."""
    entity_registry = async_get_entity_registry(hass)
    entries = entity_registry.entities.get_entries_for_config_entry_id(
        config_entry.entry_id
    )
    by_platform = Counter(entry.domain for entry in entries)
    available = 0
    unavailable = 0
    for entry in entries:
        state = hass.states.get(entry.entity_id)
        if state is None or state.state == STATE_UNAVAILABLE:
            unavailable += 1
        else:
            available += 1
    return {
        "by_platform": dict(sorted(by_platform.items())),
        "total": len(entries),
        "available": available,
        "unavailable": unavailable,
    }


def _presence_summary(area: AdaptiveArea) -> dict[str, Any]:
    """Build the current privacy-safe presence explanation."""
    sensor_ids = list(dict.fromkeys(area.get_presence_sensors()))
    sources = [safe_entity_descriptor(area.hass, entity_id) for entity_id in sensor_ids]
    domains = sorted({source["domain"] for source in sources})
    device_classes = sorted(
        {
            str(source["device_class"])
            for source in sources
            if source["device_class"] is not None
        }
    )
    config = area.config
    configured_sources = set(config.get(CONF_INCLUDE_ENTITIES, [])) | set(
        config.get(CONF_KEEP_ONLY_ENTITIES, [])
    )
    control_sources = config.get(CONF_PRESENCE_CONTROL_ENTITIES, [])
    return {
        "configured_source_count": len(configured_sources),
        "discovered_source_count": len(sources),
        "active_source_count": sum(source["active"] for source in sources),
        "source_domains": domains,
        "source_device_classes": device_classes,
        "presence_control_source_count": len(control_sources),
        "last_transition": area.last_changed.isoformat().replace("+00:00", "Z"),
        "occupancy_state": (
            AREA_STATE_OCCUPIED if area.is_occupied() else AREA_STATE_CLEAR
        ),
        "active_state_flags": sorted(str(state) for state in area.states),
        "sources": sources,
    }


def _area_summary(area: AdaptiveArea) -> dict[str, Any]:
    """Describe area semantics without names or backend IDs."""
    child_count = 0
    active_child_count = 0
    if isinstance(area, AdaptiveMetaArea):
        child_sources = area.get_presence_sensors()
        child_count = len(child_sources)
        active_child_count = sum(
            bool((state := area.hass.states.get(entity_id)) and state.state == STATE_ON)
            for entity_id in child_sources
        )
    return {
        "kind": "meta" if area.is_meta() else "regular",
        "classification": area.area_type,
        "meta_type": _meta_type(area),
        "active_states": sorted(str(state) for state in area.states),
        "primary_occupancy_state": (
            AREA_STATE_OCCUPIED if area.is_occupied() else AREA_STATE_CLEAR
        ),
        "configured_clear_timeout_minutes": area.config.get(
            CONF_CLEAR_TIMEOUT, DEFAULT_CLEAR_TIMEOUT
        ),
        "secondary_states_enabled": sorted(
            state
            for state, config_key in CONFIGURABLE_AREA_STATE_MAP.items()
            if area.config.get(CONF_SECONDARY_STATES, {}).get(config_key)
        ),
        "features": _enabled_features(area),
        "child_area_count": child_count,
        "active_child_area_count": active_child_count,
    }


def _legacy_same_area_count(hass: HomeAssistant, config_entry: ConfigEntry) -> int:
    """Count legacy entries for the same area without exposing its identifier."""
    area_id = config_entry.data.get(CONF_ID)
    return sum(
        entry.data.get(CONF_ID) == area_id
        for entry in hass.config_entries.async_entries("magic_areas")
    )


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> dict[str, Any]:
    """Return privacy-safe config-entry diagnostics in stable sections."""
    integration = await async_get_integration(hass, DOMAIN)
    runtime = hass.data.get(MODULE_DATA, {}).get(config_entry.entry_id, {})
    area: AdaptiveArea | None = runtime.get(DATA_AREA_OBJECT)
    generated = _generated_entity_summary(hass, config_entry)
    repair_summary = get_repair_summary(hass, config_entry)

    if area is None:
        enabled = config_entry.data.get(CONF_ENABLED_FEATURES, {})
        enabled_features = sorted(enabled) if isinstance(enabled, (dict, list)) else []
        return {
            "integration": {
                "name": "Adaptive Areas",
                "version": integration.version,
                "config_entry_version": config_entry.version,
                "config_entry_minor_version": config_entry.minor_version,
                "loaded": config_entry.state is ConfigEntryState.LOADED,
                "area_type": config_entry.data.get("type"),
                "meta_area_type": None,
                "enabled_feature_ids": enabled_features,
                "generated_entities": generated,
            },
            "configuration": {"stored": True, "runtime_available": False},
            "area": {"kind": "unavailable"},
            "presence": {},
            "states": {},
            "features": {"enabled": enabled_features},
            "entities": generated,
            "repairs": {
                "active_issue_count": active_issue_count(hass, config_entry),
                "summary": repair_summary,
            },
            "decision_trace": [],
            "environment": {},
        }

    enabled_features = _enabled_features(area)
    presence = _presence_summary(area)
    area_summary = _area_summary(area)
    return {
        "integration": {
            "name": "Adaptive Areas",
            "version": integration.version,
            "config_entry_version": config_entry.version,
            "config_entry_minor_version": config_entry.minor_version,
            "loaded": config_entry.state is ConfigEntryState.LOADED,
            "area_type": area.area_type,
            "meta_area_type": _meta_type(area),
            "enabled_feature_ids": enabled_features,
            "generated_entities": generated,
        },
        "configuration": {
            "runtime_available": True,
            "explicit_presence_source_count": presence["configured_source_count"],
            "presence_control_source_count": presence["presence_control_source_count"],
            "secondary_state_count": len(area_summary["secondary_states_enabled"]),
        },
        "area": area_summary,
        "presence": presence,
        "states": {
            "active": area_summary["active_states"],
            "primary": area_summary["primary_occupancy_state"],
            "secondary_enabled": area_summary["secondary_states_enabled"],
        },
        "features": {
            "enabled": enabled_features,
            "count": len(enabled_features),
        },
        "entities": {
            **generated,
            "discovered_by_platform": {
                domain: len(entities)
                for domain, entities in sorted(area.entities.items())
            },
        },
        "repairs": {
            "active_issue_count": active_issue_count(hass, config_entry),
            "summary": repair_summary,
            "legacy_same_area_entries": _legacy_same_area_count(hass, config_entry),
        },
        "decision_trace": area.decision_trace.export(),
        "environment": (
            {"enabled": True, **area.environment.diagnostics()}
            if area.environment is not None
            else {"enabled": False}
        ),
        "room_usage": (
            {"enabled": True, **area.room_usage.assessment}
            if area.room_usage is not None
            else {"enabled": False}
        ),
    }


async def async_get_device_diagnostics(
    hass: HomeAssistant, config_entry: ConfigEntry, device: DeviceEntry
) -> dict[str, Any]:
    """Return config-entry diagnostics for the entry's one-to-one area device."""
    diagnostics = await async_get_config_entry_diagnostics(hass, config_entry)
    diagnostics["device"] = {"mapping": "adaptive_area_config_entry"}
    return diagnostics
