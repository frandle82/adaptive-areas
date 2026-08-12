"""Home Assistant Repair issue detection for Adaptive Areas."""

from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.area_registry import async_get as async_get_area_registry
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from homeassistant.helpers.floor_registry import async_get as async_get_floor_registry

from custom_components.adaptive_areas.const import (
    CONF_ACCENT_ENTITY,
    CONF_ACCENT_LIGHTS,
    CONF_AREA_HUMIDITY_SENSOR,
    CONF_AREA_TEMPERATURE_SENSOR,
    CONF_BLE_TRACKER_ENTITIES,
    CONF_CLIMATE_CONTROL_ENTITY_ID,
    CONF_DARK_ENTITY,
    CONF_ID,
    CONF_INCLUDE_ENTITIES,
    CONF_ENVIRONMENT_OUTDOOR_TEMPERATURE,
    CONF_ENVIRONMENT_OUTDOOR_HUMIDITY,
    CONF_ENVIRONMENT_SURFACE_TEMPERATURE,
    CONF_ENVIRONMENT_WINDOWS,
    CONF_ENVIRONMENT_VENTILATION_FANS,
    CONF_ENVIRONMENT_CIRCULATION_FANS,
    CONF_ENVIRONMENT_DISABLED_FANS,
    CONF_KEEP_ONLY_ENTITIES,
    CONF_NOTIFICATION_DEVICES,
    CONF_OVERHEAD_LIGHTS,
    CONF_PRESENCE_CONTROL_ENTITIES,
    CONF_SLEEP_ENTITY,
    CONF_SLEEP_LIGHTS,
    CONF_SLEEP_SWITCHES,
    CONF_TASK_LIGHTS,
    CONF_TASK_SWITCHES,
    DOMAIN,
    MetaAreaType,
)

ISSUE_MISSING_AREA = "missing_area"
ISSUE_MISSING_ENTITIES = "missing_entities"

_ENTITY_REFERENCE_CATEGORIES = {
    CONF_AREA_TEMPERATURE_SENSOR: "area_climate",
    CONF_AREA_HUMIDITY_SENSOR: "area_climate",
    CONF_INCLUDE_ENTITIES: "area_filter",
    CONF_KEEP_ONLY_ENTITIES: "presence",
    CONF_PRESENCE_CONTROL_ENTITIES: "presence",
    CONF_DARK_ENTITY: "secondary_states",
    CONF_SLEEP_ENTITY: "secondary_states",
    CONF_ACCENT_ENTITY: "secondary_states",
    CONF_OVERHEAD_LIGHTS: "light_groups",
    CONF_TASK_LIGHTS: "light_groups",
    CONF_ACCENT_LIGHTS: "light_groups",
    CONF_SLEEP_LIGHTS: "light_groups",
    CONF_TASK_SWITCHES: "switch_groups",
    CONF_SLEEP_SWITCHES: "switch_groups",
    CONF_CLIMATE_CONTROL_ENTITY_ID: "climate_control",
    CONF_BLE_TRACKER_ENTITIES: "ble_trackers",
    CONF_NOTIFICATION_DEVICES: "area_aware_media_player",
    CONF_ENVIRONMENT_OUTDOOR_TEMPERATURE: "area_evaluation",
    CONF_ENVIRONMENT_OUTDOOR_HUMIDITY: "area_evaluation",
    CONF_ENVIRONMENT_SURFACE_TEMPERATURE: "area_evaluation",
    CONF_ENVIRONMENT_WINDOWS: "area_evaluation",
    CONF_ENVIRONMENT_VENTILATION_FANS: "area_evaluation",
    CONF_ENVIRONMENT_CIRCULATION_FANS: "area_evaluation",
    CONF_ENVIRONMENT_DISABLED_FANS: "area_evaluation",
}


def _issue_id(category: str, entry_id: str) -> str:
    """Return a deterministic issue ID for a config entry."""
    return f"{category}_{entry_id}"


def _combined_config(config_entry: ConfigEntry) -> dict[str, Any]:
    """Return data overlaid with options, matching runtime behavior."""
    config = dict(config_entry.data)
    config.update(config_entry.options)
    return config


def _iter_entity_references(
    value: Any, *, category: str = "configuration"
) -> Iterable[tuple[str, str]]:
    """Yield configured entity IDs and their safe feature categories."""
    if not isinstance(value, dict):
        return
    for key, item in value.items():
        item_category = _ENTITY_REFERENCE_CATEGORIES.get(key, category)
        if key in _ENTITY_REFERENCE_CATEGORIES:
            values = item if isinstance(item, list) else [item]
            for entity_id in values:
                if isinstance(entity_id, str) and "." in entity_id:
                    yield entity_id, item_category
            continue
        if isinstance(item, dict):
            yield from _iter_entity_references(item, category=str(key))


def get_missing_entity_summary(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> dict[str, Any]:
    """Return counts and categories for truly absent configured entities."""
    entity_registry = async_get_entity_registry(hass)
    missing_by_category: dict[str, int] = defaultdict(int)
    seen: set[str] = set()
    for entity_id, category in _iter_entity_references(_combined_config(config_entry)):
        if entity_id in seen:
            continue
        seen.add(entity_id)
        if hass.states.get(entity_id) is not None:
            continue
        if entity_registry.async_get(entity_id) is not None:
            continue
        missing_by_category[category] += 1
    return {
        "count": sum(missing_by_category.values()),
        "categories": sorted(missing_by_category),
        "category_counts": dict(sorted(missing_by_category.items())),
    }


def get_configured_entity_references(config_entry: ConfigEntry) -> set[str]:
    """Return explicit references used by Repair and registry reload checks."""
    return {
        entity_id
        for entity_id, _category in _iter_entity_references(
            _combined_config(config_entry)
        )
    }


def config_entry_area_exists(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Return whether the regular or meta area backing an entry still exists."""
    area_id = config_entry.data.get(CONF_ID)
    if area_id in {
        MetaAreaType.GLOBAL,
        MetaAreaType.INTERIOR,
        MetaAreaType.EXTERIOR,
    }:
        return True
    if async_get_floor_registry(hass).async_get_floor(area_id) is not None:
        return True
    return async_get_area_registry(hass).async_get_area(area_id) is not None


def get_repair_summary(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> dict[str, Any]:
    """Build a privacy-safe repair summary without changing issue state."""
    missing_entities = get_missing_entity_summary(hass, config_entry)
    return {
        "missing_area": not config_entry_area_exists(hass, config_entry),
        "missing_entities": missing_entities,
    }


async def async_evaluate_config_entry(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> dict[str, Any]:
    """Create and clear deterministic issues for one config entry."""
    summary = get_repair_summary(hass, config_entry)
    missing_area_id = _issue_id(ISSUE_MISSING_AREA, config_entry.entry_id)
    missing_entities_id = _issue_id(ISSUE_MISSING_ENTITIES, config_entry.entry_id)

    if summary["missing_area"]:
        ir.async_create_issue(
            hass,
            DOMAIN,
            missing_area_id,
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key=ISSUE_MISSING_AREA,
            translation_placeholders={"entry": config_entry.title},
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, missing_area_id)

    missing_entities = summary["missing_entities"]
    if missing_entities["count"]:
        ir.async_create_issue(
            hass,
            DOMAIN,
            missing_entities_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_MISSING_ENTITIES,
            translation_placeholders={
                "entry": config_entry.title,
                "count": str(missing_entities["count"]),
                "category_count": str(len(missing_entities["categories"])),
            },
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, missing_entities_id)
    return summary


def active_issue_count(hass: HomeAssistant) -> int:
    """Return the number of active Adaptive Areas issues."""
    registry = ir.async_get(hass)
    return sum(
        issue.active
        for (domain, _issue_id_value), issue in registry.issues.items()
        if domain == DOMAIN
    )


async def async_remove_config_entry_issues(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> None:
    """Remove issues after the corresponding config entry is deleted."""
    for category in (ISSUE_MISSING_AREA, ISSUE_MISSING_ENTITIES):
        ir.async_delete_issue(hass, DOMAIN, _issue_id(category, config_entry.entry_id))
