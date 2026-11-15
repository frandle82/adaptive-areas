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
    _generated_states,
    build_area_detail,
    build_area_summary,
    build_diagnostics,
    build_overview,
)


def _get_area(hass: HomeAssistant, area_id: str):
    for area in _areas(hass):
        if str(area.id) == area_id:
            return area
    raise HomeAssistantError("Adaptive Area not found")


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "adaptive_areas/get_overview"})
@websocket_api.async_response
async def websocket_get_overview(hass, connection, msg):
    """Return the compact dashboard overview."""
    connection.send_result(msg["id"], build_overview(hass))


@websocket_api.require_admin
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
        websocket_subscribe_updates,
    ):
        websocket_api.async_register_command(hass, command)
    hass.data[key] = True
