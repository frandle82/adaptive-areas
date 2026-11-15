"""Read-only WebSocket commands for the Adaptive Areas dashboard."""

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.loader import async_get_integration

from custom_components.adaptive_areas.dashboard import (
    _areas,
    _area_sources,
    _controls,
    _generated_states,
    build_area_detail,
    build_area_summary,
    build_diagnostics,
    build_overview,
)
from custom_components.adaptive_areas.area_config import (
    area_configuration,
    async_create_area,
    async_update_area,
    available_areas,
)
from custom_components.adaptive_areas.const import DOMAIN


def _get_area(hass: HomeAssistant, area_id: str):
    for area in _areas(hass):
        if str(area.id) == area_id:
            return area
    raise HomeAssistantError("Adaptive Area not found")


def _get_entry(hass: HomeAssistant, entry_id: str):
    """Return an Adaptive Areas ConfigEntry or reject foreign IDs."""
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        raise HomeAssistantError("Adaptive Area config entry not found")
    return entry


@websocket_api.websocket_command({vol.Required("type"): "adaptive_areas/get_overview"})
@websocket_api.async_response
async def websocket_get_overview(hass, connection, msg):
    """Return the compact dashboard overview."""
    connection.send_result(msg["id"], build_overview(hass))


@websocket_api.websocket_command(
    {vol.Required("type"): "adaptive_areas/get_area", vol.Required("area_id"): str}
)
@websocket_api.async_response
async def websocket_get_area(hass, connection, msg):
    """Return one detailed read-only area snapshot."""
    connection.send_result(
        msg["id"], build_area_detail(hass, _get_area(hass, msg["area_id"]))
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): "adaptive_areas/get_diagnostics"}
)
@websocket_api.async_response
async def websocket_get_diagnostics(hass, connection, msg):
    """Return compact dashboard diagnostics."""
    integration = await async_get_integration(hass, "adaptive_areas")
    connection.send_result(msg["id"], build_diagnostics(hass, integration.version))


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): "adaptive_areas/get_area_configuration"}
)
@websocket_api.async_response
async def websocket_get_area_configuration(hass, connection, msg):
    """Return persisted Area configurations and unused HA Areas for admin editing."""
    connection.send_result(
        msg["id"],
        {
            "areas": [
                area_configuration(entry)
                for entry in hass.config_entries.async_entries(DOMAIN)
            ],
            "available_areas": available_areas(hass),
        },
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "adaptive_areas/create_area",
        vol.Required("area_id"): str,
        vol.Optional("options", default={}): dict,
    }
)
@websocket_api.async_response
async def websocket_create_area(hass, connection, msg):
    """Create a ConfigEntry-backed regular Area after schema validation."""
    entry, errors = await async_create_area(hass, msg["area_id"], msg["options"])
    connection.send_result(
        msg["id"],
        {
            "ok": entry is not None,
            "errors": errors,
            "area": area_configuration(entry) if entry else None,
        },
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "adaptive_areas/update_area",
        vol.Required("entry_id"): str,
        vol.Required("options"): dict,
    }
)
@websocket_api.async_response
async def websocket_update_area(hass, connection, msg):
    """Persist a complete Area options snapshot and reload the entry once."""
    errors = await async_update_area(
        hass, _get_entry(hass, msg["entry_id"]), msg["options"]
    )
    connection.send_result(msg["id"], {"ok": not errors, "errors": errors})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): "adaptive_areas/delete_area", vol.Required("entry_id"): str}
)
@websocket_api.async_response
async def websocket_delete_area(hass, connection, msg):
    """Delete one Area through the normal ConfigEntry lifecycle."""
    entry = _get_entry(hass, msg["entry_id"])
    await hass.config_entries.async_remove(entry.entry_id)
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.websocket_command(
    {vol.Required("type"): "adaptive_areas/subscribe_updates"}
)
@websocket_api.async_response
async def websocket_subscribe_updates(hass, connection, msg):
    """Send changed area summaries for tracked runtime entities only."""
    entity_to_area = {
        entity_id: area
        for area in _areas(hass)
        for entity_id in {
            *_area_sources(area),
            *(state["entity_id"] for state in _generated_states(hass, area)),
            *area.get_presence_sensors(),
            *(
                control["entity_id"]
                for group in _controls(hass, area)
                for control in group["controls"]
            ),
        }
    }

    @callback
    def _state_changed(event) -> None:
        entity_id = event.data["entity_id"]
        if area := entity_to_area.get(entity_id):
            connection.send_event(msg["id"], {"area": build_area_summary(hass, area)})

    remove_listener = lambda: None
    if entity_to_area:
        remove_listener = async_track_state_change_event(
            hass, list(entity_to_area), _state_changed
        )
    connection.subscriptions[msg["id"]] = remove_listener
    connection.send_result(msg["id"])


@callback
def async_register_websocket_commands(hass: HomeAssistant) -> None:
    """Register the command set once for all config entries."""
    key = "adaptive_areas_dashboard_websocket_registered"
    if hass.data.get(key):
        return
    for command in (
        websocket_get_overview,
        websocket_get_area,
        websocket_get_diagnostics,
        websocket_get_area_configuration,
        websocket_create_area,
        websocket_update_area,
        websocket_delete_area,
        websocket_subscribe_updates,
    ):
        websocket_api.async_register_command(hass, command)
    hass.data[key] = True
