"""Dashboard subscription follows the set of loaded Areas (B10) and the live role (R01)."""

import json
from types import SimpleNamespace

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant

from custom_components.adaptive_areas.const import DATA_AREA_OBJECT, MODULE_DATA
from custom_components.adaptive_areas.helpers.area import iter_runtime_areas
from custom_components.adaptive_areas.websocket import async_register_websocket_commands
from tests.helpers import init_integration, shutdown_integration
from tests.test_dashboard_permissions import ENTITY_ID_PATTERN


class _Connection:
    """Minimal WebSocket connection that records pushed events."""

    def __init__(self, *, is_admin: bool = True) -> None:
        self.user = SimpleNamespace(is_admin=is_admin)
        self.events: list[dict] = []
        self.subscriptions: dict = {}

    def send_result(self, _msg_id, result=None) -> None:
        return None

    def send_error(self, _msg_id, code, message) -> None:
        raise AssertionError(f"unexpected error {code}: {message}")

    def send_event(self, _msg_id, event) -> None:
        self.events.append(event)


async def _subscribe(hass: HomeAssistant, connection: _Connection) -> None:
    handler, schema = hass.data["websocket_api"]["adaptive_areas/subscribe_updates"]
    message = {"id": 1, "type": "adaptive_areas/subscribe_updates"}
    handler(hass, connection, message if schema is False else schema(message))
    await hass.async_block_till_done()


def _presence_entity(area) -> str:
    return f"binary_sensor.adaptive_areas_presence_tracking_{area.slug}_area_state"


def _area_events(connection: _Connection) -> list[dict]:
    return [event["area"] for event in connection.events if "area" in event]


async def test_subscription_follows_added_and_removed_areas(
    hass: HomeAssistant, basic_config_entry: MockConfigEntry
) -> None:
    """An Area loaded after subscribing pushes updates; an unloaded Area stops."""
    async_register_websocket_commands(hass)
    connection = _Connection()
    await _subscribe(hass, connection)
    assert connection.events == []

    await init_integration(hass, [basic_config_entry])
    assert {"areas_changed": True} in connection.events
    area = hass.data[MODULE_DATA][basic_config_entry.entry_id][DATA_AREA_OBJECT]

    connection.events.clear()
    hass.states.async_set(_presence_entity(area), "on")
    await hass.async_block_till_done()
    assert [summary["id"] for summary in _area_events(connection)] == [area.id]

    connection.events.clear()
    assert await hass.config_entries.async_unload(basic_config_entry.entry_id)
    await hass.async_block_till_done()
    assert {"areas_changed": True} in connection.events

    connection.events.clear()
    hass.states.async_set(_presence_entity(area), "off")
    await hass.async_block_till_done()
    assert _area_events(connection) == []

    connection.subscriptions[1]()
    connection.events.clear()
    assert await hass.config_entries.async_setup(basic_config_entry.entry_id)
    await hass.async_block_till_done()
    assert connection.events == [], "a closed subscription must not receive events"
    await shutdown_integration(hass, [basic_config_entry])


async def test_areas_changed_event_carries_no_data(
    hass: HomeAssistant, basic_config_entry: MockConfigEntry
) -> None:
    """The structural event is data-free, also for non-administrators."""
    async_register_websocket_commands(hass)
    connection = _Connection(is_admin=False)
    await _subscribe(hass, connection)
    await init_integration(hass, [basic_config_entry])

    structural = [event for event in connection.events if "areas_changed" in event]
    assert structural and all(event == {"areas_changed": True} for event in structural)
    connection.subscriptions[1]()
    await shutdown_integration(hass, [basic_config_entry])


async def test_shared_entity_updates_every_area(
    hass: HomeAssistant, _setup_integration_all_areas_with_meta
) -> None:
    """An entity tracked by a child and its Meta Areas updates each of them."""
    connection = _Connection()
    await _subscribe(hass, connection)
    areas = list(iter_runtime_areas(hass))
    child = next(area for area in areas if not area.is_meta())
    tracked_by = [
        area
        for area in areas
        if area.is_meta()
        and _presence_entity(child) in set(area.get_presence_sensors())
    ]
    assert tracked_by, "fixture must contain a Meta Area that tracks the child"

    hass.states.async_set(_presence_entity(child), "on")
    await hass.async_block_till_done()
    updated = {summary["id"] for summary in _area_events(connection)}
    assert child.id in updated
    assert {area.id for area in tracked_by} <= updated
    connection.subscriptions[1]()


async def test_subscription_reads_the_role_for_every_event(
    hass: HomeAssistant,
    basic_config_entry: MockConfigEntry,
    entities_binary_sensor_motion_one,
) -> None:
    """A demoted user stops receiving administrator detail on a live subscription.

    Home Assistant updates ``connection.user`` in place when groups change and keeps
    the connection open, so the role must not be captured at subscription time.
    """
    async_register_websocket_commands(hass)
    await init_integration(hass, [basic_config_entry])
    area = hass.data[MODULE_DATA][basic_config_entry.entry_id][DATA_AREA_OBJECT]
    connection = _Connection(is_admin=True)
    await _subscribe(hass, connection)

    hass.states.async_set(_presence_entity(area), "on")
    await hass.async_block_till_done()
    assert any("controls" in summary for summary in _area_events(connection))

    connection.user.is_admin = False
    connection.events.clear()
    # A real source change alters the summary, so an update is sent for either role.
    hass.states.async_set(entities_binary_sensor_motion_one[0].entity_id, "unavailable")
    await hass.async_block_till_done()
    demoted = _area_events(connection)
    assert demoted, "a source change must produce an update"
    assert all("controls" not in summary for summary in demoted)
    assert ENTITY_ID_PATTERN.search(json.dumps(demoted)) is None

    connection.subscriptions[1]()
    await shutdown_integration(hass, [basic_config_entry])
