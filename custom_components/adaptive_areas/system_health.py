"""Native Home Assistant System Health support for Adaptive Areas."""

from homeassistant.components import system_health
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers.floor_registry import async_get as async_get_floor_registry
from homeassistant.loader import async_get_integration

from custom_components.adaptive_areas.const import (
    AREA_TYPE_EXTERIOR,
    AREA_TYPE_INTERIOR,
    AREA_TYPE_META,
    CONF_ID,
    CONF_FEATURE_ENVIRONMENT,
    CONF_FEATURE_ROOM_USAGE,
    CONF_TYPE,
    DATA_AREA_OBJECT,
    DOMAIN,
    MODULE_DATA,
)
from custom_components.adaptive_areas.repairs import active_issue_count


async def async_register(
    hass: HomeAssistant, register: system_health.SystemHealthRegistration
) -> None:
    """Register Adaptive Areas system health information."""
    register.async_register_info(async_system_health_info)


async def async_system_health_info(hass: HomeAssistant) -> dict[str, object]:
    """Return a privacy-safe integration-wide summary."""
    integration = await async_get_integration(hass, DOMAIN)
    entries = hass.config_entries.async_entries(DOMAIN)
    floor_registry = async_get_floor_registry(hass)
    floor_ids = {floor.floor_id for floor in floor_registry.async_list_floors()}

    regular_entries = [
        entry for entry in entries if entry.data.get(CONF_TYPE) != AREA_TYPE_META
    ]
    meta_entries = [
        entry for entry in entries if entry.data.get(CONF_TYPE) == AREA_TYPE_META
    ]
    runtime_areas = [
        runtime[DATA_AREA_OBJECT]
        for runtime in hass.data.get(MODULE_DATA, {}).values()
        if DATA_AREA_OBJECT in runtime and not runtime[DATA_AREA_OBJECT].is_meta()
    ]
    cleaning_assessments = [
        area.room_usage.assessment
        for area in runtime_areas
        if area.room_usage is not None
    ]
    return {
        "version": integration.version,
        "configured_entries": len(entries),
        "loaded_entries": sum(
            entry.state is ConfigEntryState.LOADED for entry in entries
        ),
        "regular_areas": len(regular_entries),
        "meta_areas": len(meta_entries),
        "interior_areas": sum(
            entry.data.get(CONF_TYPE) == AREA_TYPE_INTERIOR for entry in regular_entries
        ),
        "exterior_areas": sum(
            entry.data.get(CONF_TYPE) == AREA_TYPE_EXTERIOR for entry in regular_entries
        ),
        "floor_meta_areas": sum(
            entry.data.get(CONF_ID) in floor_ids for entry in meta_entries
        ),
        "active_repairs": active_issue_count(hass),
        "environment_areas": sum(
            area.has_feature(CONF_FEATURE_ENVIRONMENT) for area in runtime_areas
        ),
        "room_usage_areas": sum(
            area.has_feature(CONF_FEATURE_ROOM_USAGE) for area in runtime_areas
        ),
        "areas_with_cleaning_due": sum(
            bool(assessment.get("due")) for assessment in cleaning_assessments
        ),
        "areas_with_cleaning_overdue": sum(
            assessment.get("cleaning_state") == "overdue"
            for assessment in cleaning_assessments
        ),
        "areas_without_presence_sources": sum(
            not area.get_presence_sensors() for area in runtime_areas
        ),
        "legacy_magic_areas_entries": len(
            hass.config_entries.async_entries("magic_areas")
        ),
    }
