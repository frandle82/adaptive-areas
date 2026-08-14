"""Services for the Adaptive Areas Cleaning Tracker."""

from collections.abc import Awaitable, Callable
from typing import Any

import voluptuous as vol

from homeassistant.const import ATTR_AREA_ID
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
import homeassistant.helpers.config_validation as cv

from custom_components.adaptive_areas.const import (
    ATTR_SCORE,
    DATA_AREA_OBJECT,
    DOMAIN,
    MODULE_DATA,
    SERVICE_MARK_CLEANED,
    SERVICE_RESET,
    SERVICE_SET_SCORE,
)

AREA_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_AREA_ID): vol.All(
            cv.ensure_list,
            [cv.string],
            vol.Length(min=1),
        )
    }
)
SET_SCORE_SERVICE_SCHEMA = AREA_SERVICE_SCHEMA.extend(
    {
        vol.Required(ATTR_SCORE): vol.All(
            vol.Coerce(float),
            vol.Range(min=0, max=100),
        )
    }
)


def _trackers_for_call(hass: HomeAssistant, call: ServiceCall) -> list[Any]:
    """Resolve all requested Area trackers before mutating any of them."""
    requested_ids = list(dict.fromkeys(call.data[ATTR_AREA_ID]))
    trackers_by_area = {
        area.id: area.room_usage
        for entry_data in hass.data.get(MODULE_DATA, {}).values()
        if (area := entry_data[DATA_AREA_OBJECT]).room_usage is not None
    }
    missing = [area_id for area_id in requested_ids if area_id not in trackers_by_area]
    if missing:
        raise ServiceValidationError(
            "Cleaning Tracker is not enabled for Area(s): " + ", ".join(missing)
        )
    return [trackers_by_area[area_id] for area_id in requested_ids]


async def _async_apply(
    hass: HomeAssistant,
    call: ServiceCall,
    operation: Callable[[Any], Awaitable[None]],
) -> None:
    """Apply an operation to all validated target Areas."""
    trackers = _trackers_for_call(hass, call)
    for tracker in trackers:
        await operation(tracker)


def async_setup_services(hass: HomeAssistant) -> None:
    """Register Cleaning Tracker services once."""
    if hass.services.has_service(DOMAIN, SERVICE_MARK_CLEANED):
        return

    async def async_mark_cleaned(call: ServiceCall) -> None:
        await _async_apply(hass, call, lambda tracker: tracker.async_mark_cleaned())

    async def async_reset(call: ServiceCall) -> None:
        await _async_apply(hass, call, lambda tracker: tracker.async_reset())

    async def async_set_score(call: ServiceCall) -> None:
        score = call.data[ATTR_SCORE]
        await _async_apply(
            hass,
            call,
            lambda tracker: tracker.async_set_score(score),
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_MARK_CLEANED,
        async_mark_cleaned,
        schema=AREA_SERVICE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_RESET,
        async_reset,
        schema=AREA_SERVICE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_SCORE,
        async_set_score,
        schema=SET_SCORE_SERVICE_SCHEMA,
    )


def async_unload_services(hass: HomeAssistant) -> None:
    """Remove Cleaning Tracker services when the integration is fully unloaded."""
    for service in (SERVICE_MARK_CLEANED, SERVICE_RESET, SERVICE_SET_SCORE):
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)
