"""Read-only WebSocket commands for the Adaptive Areas dashboard."""

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.components.sensor.const import SensorDeviceClass
from homeassistant.const import LIGHT_LUX as LIGHT_LUX_UNIT
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.loader import async_get_integration

from custom_components.adaptive_areas.dashboard import (
    _areas,
    _area_sources,
    _controls,
    _generated_states,
    build_area_detail,
    build_decision_trace,
    build_climate_runtime_status,
    build_light_runtime_status,
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
    SIGNAL_AREAS_CHANGED,
)
from custom_components.adaptive_areas.dashboard_texts import load_dashboard_texts
from custom_components.adaptive_areas.migration import get_global_entries


def is_illuminance_state(state) -> bool:
    """Accept illuminance device class or the exact lx unit; never convert others."""
    attributes = state.attributes
    return (
        attributes.get("device_class") == SensorDeviceClass.ILLUMINANCE
        or attributes.get("unit_of_measurement") == LIGHT_LUX_UNIT
    )


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
        elif not is_illuminance_state(state):
            errors[CONF_GLOBAL_LIGHT_SENSOR] = "Expected an illuminance sensor"
    return errors


def _is_admin(connection) -> bool:
    """Fail closed: only an explicit administrator receives entity-level detail."""
    return bool(getattr(getattr(connection, "user", None), "is_admin", False))


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
    """Return the compact dashboard overview; entity detail only for administrators."""
    connection.send_result(
        msg["id"], build_overview(hass, include_entities=_is_admin(connection))
    )


@websocket_api.websocket_command(
    {vol.Required("type"): "adaptive_areas/get_area", vol.Required("area_id"): str}
)
@websocket_api.async_response
async def websocket_get_area(hass, connection, msg):
    """Return one detailed read-only area snapshot."""
    connection.send_result(
        msg["id"],
        build_area_detail(
            hass,
            _get_area(hass, msg["area_id"]),
            include_entities=_is_admin(connection),
        ),
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "adaptive_areas/get_decision_trace",
        vol.Required("area_id"): str,
        vol.Optional("limit", default=20): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=20)
        ),
    }
)
@websocket_api.async_response
async def websocket_get_decision_trace(hass, connection, msg):
    """Return the in-memory decision trace of one area (administrators only)."""
    connection.send_result(
        msg["id"],
        build_decision_trace(_get_area(hass, msg["area_id"]), msg["limit"]),
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
    {
        vol.Required("type"): "adaptive_areas/get_light_runtime_status",
        vol.Required("area_id"): str,
    }
)
@websocket_api.async_response
async def websocket_get_light_runtime_status(hass, connection, msg):
    """Return the current, non-mutating Light runtime snapshot for one Area."""
    connection.send_result(
        msg["id"], build_light_runtime_status(hass, _get_area(hass, msg["area_id"]))
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "adaptive_areas/get_climate_runtime_status",
        vol.Required("area_id"): str,
    }
)
@websocket_api.async_response
async def websocket_get_climate_runtime_status(hass, connection, msg):
    """Return the current, non-mutating Climate runtime snapshot for one Area."""
    connection.send_result(
        msg["id"], build_climate_runtime_status(hass, _get_area(hass, msg["area_id"]))
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
    current = get_global_options(entry)
    # Only new or changed values are validated; unchanged stored entities are kept
    # even when they are currently unavailable. Explicit None still clears a field.
    changed = {
        key: value for key, value in updates.items() if current.get(key) != value
    }
    if errors := _validate_global_options(hass, changed):
        connection.send_result(msg["id"], {"ok": False, "errors": errors})
        return
    if not changed:
        connection.send_result(
            msg["id"], {"ok": True, "errors": {}, "options": current}
        )
        return
    update_global_options(hass, entry, changed)
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
    details: dict[str, dict[str, str]] = {}
    errors = await async_update_area(hass, msg["area_id"], msg["options"], details)
    connection.send_result(
        msg["id"], {"ok": not errors, "errors": errors, "details": details}
    )


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
    """Send changed area summaries for tracked runtime entities only.

    The entity index is rebuilt whenever the set of loaded Areas changes, and the
    client receives a data-free ``areas_changed`` event so it can reload the
    overview. An entity shared by several Areas (for example a child and its Meta
    Area) updates every one of them.

    The role is read for every event: Home Assistant updates ``connection.user``
    in place when a user's groups change and keeps the connection open, so a
    role captured at subscription time could go stale.
    """
    last_summaries: dict[str, dict] = {}
    entity_to_areas: dict[str, list] = {}
    remove_state_listener = lambda: None

    def _index() -> dict[str, list]:
        index: dict[str, list] = {}
        for area in _areas(hass):
            for entity_id in {
                *_area_sources(area),
                *(state["entity_id"] for state in _generated_states(hass, area)),
                *area.get_presence_sensors(),
                *(
                    control["entity_id"]
                    for group in _controls(hass, area)
                    for control in group["controls"]
                ),
            }:
                index.setdefault(entity_id, []).append(area)
        return index

    @callback
    def _state_changed(event) -> None:
        for area in entity_to_areas.get(event.data["entity_id"], ()):
            summary = build_area_summary(hass, area, _is_admin(connection))
            if last_summaries.get(summary["id"]) == summary:
                continue
            last_summaries[summary["id"]] = summary
            connection.send_event(msg["id"], {"area": summary})

    @callback
    def _track() -> None:
        nonlocal entity_to_areas, remove_state_listener
        remove_state_listener()
        entity_to_areas = _index()
        remove_state_listener = (
            async_track_state_change_event(hass, list(entity_to_areas), _state_changed)
            if entity_to_areas
            else (lambda: None)
        )

    @callback
    def _areas_changed() -> None:
        _track()
        last_summaries.clear()
        connection.send_event(msg["id"], {"areas_changed": True})

    _track()
    remove_signal = async_dispatcher_connect(hass, SIGNAL_AREAS_CHANGED, _areas_changed)

    @callback
    def _unsubscribe() -> None:
        remove_signal()
        remove_state_listener()

    connection.subscriptions[msg["id"]] = _unsubscribe
    connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): "adaptive_areas/get_dashboard_texts",
        vol.Required("language"): str,
    }
)
@websocket_api.async_response
async def websocket_get_dashboard_texts(hass, connection, msg):
    """Return the dashboard texts for the panel; available to every signed-in user."""
    try:
        resources = await hass.async_add_executor_job(
            load_dashboard_texts, msg["language"]
        )
    except OSError, ValueError, TypeError:
        connection.send_error(
            msg["id"],
            "dashboard_texts_unavailable",
            "Dashboard texts could not be loaded.",
        )
        return
    connection.send_result(msg["id"], {"resources": resources})


@callback
def async_register_websocket_commands(hass: HomeAssistant) -> None:
    """Register the command set once for all config entries."""
    key = "adaptive_areas_dashboard_websocket_registered"
    if hass.data.get(key):
        return
    for command in (
        websocket_get_overview,
        websocket_get_area,
        websocket_get_decision_trace,
        websocket_get_diagnostics,
        websocket_get_area_configuration,
        websocket_get_light_runtime_status,
        websocket_get_climate_runtime_status,
        websocket_get_global_configuration,
        websocket_update_global_configuration,
        websocket_create_area,
        websocket_update_area,
        websocket_delete_area,
        websocket_subscribe_updates,
        websocket_get_dashboard_texts,
    ):
        websocket_api.async_register_command(hass, command)
    hass.data[key] = True
