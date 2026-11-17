"""Read-only WebSocket commands for the Adaptive Areas dashboard."""

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.components.sensor.const import SensorDeviceClass
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
    area_configurations,
    async_create_area,
    async_delete_area,
    async_update_area,
    available_areas,
    get_global_options,
    update_global_options,
)
from custom_components.adaptive_areas.const import (
    CONF_GLOBAL_LIGHT_SENSOR,
    CONF_WEATHER_ENTITY,
    DOMAIN,
)
from custom_components.adaptive_areas.migration import get_global_entries


def _validate_global_options(hass: HomeAssistant, updates: dict) -> dict[str, str]:
    """Validate only global-option fields explicitly supplied by the client."""
    errors = {}
    weather = updates.get(CONF_WEATHER_ENTITY)
    if CONF_WEATHER_ENTITY in updates and weather is not None:
        if not isinstance(weather, str) or not weather.startswith("weather."):
            errors[CONF_WEATHER_ENTITY] = "Expected an existing weather entity"
        elif hass.states.get(weather) is None:
            errors[CONF_WEATHER_ENTITY] = "Unknown weather entity"
    light_sensor = updates.get(CONF_GLOBAL_LIGHT_SENSOR)
    if CONF_GLOBAL_LIGHT_SENSOR in updates and light_sensor is not None:
        state = hass.states.get(light_sensor) if isinstance(light_sensor, str) else None
        if not isinstance(light_sensor, str) or not light_sensor.startswith("sensor."):
            errors[CONF_GLOBAL_LIGHT_SENSOR] = "Expected an illuminance sensor"
        elif state is None:
            errors[CONF_GLOBAL_LIGHT_SENSOR] = "Unknown illuminance sensor"
        elif state.attributes.get("device_class") != SensorDeviceClass.ILLUMINANCE:
            errors[CONF_GLOBAL_LIGHT_SENSOR] = "Expected an illuminance sensor"
    return errors


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
            "areas": sorted(
                (
                    configuration
                    for entry in hass.config_entries.async_entries(DOMAIN)
                    for configuration in area_configurations(entry)
                ),
                key=lambda configuration: configuration["area_id"],
            ),
            "available_areas": available_areas(hass),
        },
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): "adaptive_areas/get_global_configuration"}
)
@websocket_api.async_response
async def websocket_get_global_configuration(hass, connection, msg):
    """Return global options without mutating or reloading the container."""
    entries = get_global_entries(hass)
    if len(entries) != 1:
        connection.send_result(
            msg["id"],
            {"ok": False, "errors": {"base": "Exactly one GlobalEntry is required"}},
        )
        return
    options = get_global_options(entries[0])
    connection.send_result(
        msg["id"],
        {
            "ok": True,
            "errors": {},
            "options": {
                CONF_WEATHER_ENTITY: options.get(CONF_WEATHER_ENTITY),
                CONF_GLOBAL_LIGHT_SENSOR: options.get(CONF_GLOBAL_LIGHT_SENSOR),
            },
        },
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "adaptive_areas/update_global_configuration",
        vol.Required("options"): dict,
    }
)
@websocket_api.async_response
async def websocket_update_global_configuration(hass, connection, msg):
    """Persist partial global options and reload only for a real mutation."""
    updates = msg["options"]
    allowed = {CONF_WEATHER_ENTITY, CONF_GLOBAL_LIGHT_SENSOR}
    if not updates or set(updates) - allowed:
        connection.send_result(
            msg["id"], {"ok": False, "errors": {"base": "Unsupported global option"}}
        )
        return
    entries = get_global_entries(hass)
    if len(entries) != 1:
        connection.send_result(
            msg["id"],
            {"ok": False, "errors": {"base": "Exactly one GlobalEntry is required"}},
        )
        return
    entry = entries[0]
    if errors := _validate_global_options(hass, updates):
        connection.send_result(msg["id"], {"ok": False, "errors": errors})
        return
    current = get_global_options(entry)
    if all(current.get(key) == value for key, value in updates.items()):
        connection.send_result(
            msg["id"], {"ok": True, "errors": {}, "options": current}
        )
        return
    update_global_options(hass, entry, updates)
    await hass.async_block_till_done()
    connection.send_result(
        msg["id"], {"ok": True, "errors": {}, "options": get_global_options(entry)}
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
            "area": (
                area_configuration(entry, entry.options["areas"][msg["area_id"]])
                if entry
                else None
            ),
        },
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "adaptive_areas/update_area",
        vol.Required("area_id"): str,
        vol.Required("options"): dict,
    }
)
@websocket_api.async_response
async def websocket_update_area(hass, connection, msg):
    """Persist a complete logical Area snapshot and reload the container once."""
    errors = await async_update_area(hass, msg["area_id"], msg["options"])
    connection.send_result(msg["id"], {"ok": not errors, "errors": errors})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): "adaptive_areas/delete_area", vol.Required("area_id"): str}
)
@websocket_api.async_response
async def websocket_delete_area(hass, connection, msg):
    """Delete one logical Area without deleting the GlobalEntry."""
    errors = await async_delete_area(hass, msg["area_id"])
    connection.send_result(msg["id"], {"ok": not errors, "errors": errors})


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
    last_summaries: dict[str, dict] = {}

    @callback
    def _state_changed(event) -> None:
        entity_id = event.data["entity_id"]
        if area := entity_to_area.get(entity_id):
            summary = build_area_summary(hass, area)
            if last_summaries.get(summary["id"]) == summary:
                return
            last_summaries[summary["id"]] = summary
            connection.send_event(msg["id"], {"area": summary})

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
        websocket_get_global_configuration,
        websocket_update_global_configuration,
        websocket_create_area,
        websocket_update_area,
        websocket_delete_area,
        websocket_subscribe_updates,
    ):
        websocket_api.async_register_command(hass, command)
    hass.data[key] = True
