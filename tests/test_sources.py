"""Tests for domain-specific presence source discovery and evaluation."""

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.components.binary_sensor import DOMAIN as BINARY_SENSOR_DOMAIN
from homeassistant.const import STATE_OFF, STATE_ON, STATE_OPEN, STATE_PLAYING
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_component import DATA_INSTANCES
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry

from custom_components.adaptive_areas.const import (
    CONF_CLEAR_TIMEOUT,
    CONF_INCLUDE_ENTITIES,
    CONF_KEEP_ONLY_ENTITIES,
    CONF_PRESENCE_CONTROL_ENTITIES,
    CONF_PRESENCE_DEVICE_PLATFORMS,
    DOMAIN,
    AdaptiveAreasEvents,
    AdaptiveConfigEntryVersion,
)
from custom_components.adaptive_areas.helpers.sources import is_presence_source_active

from tests.const import DEFAULT_MOCK_AREA, MockAreaIds
from tests.helpers import (
    get_basic_config_entry_data,
    init_integration,
    shutdown_integration,
)


@pytest.mark.parametrize(
    ("entity_id", "state", "expected"),
    [
        ("binary_sensor.motion", STATE_ON, True),
        ("binary_sensor.door", STATE_OPEN, True),
        ("binary_sensor.motion", "off", False),
        ("media_player.tv", STATE_PLAYING, True),
        ("media_player.tv", STATE_ON, True),
        ("media_player.tv", "paused", False),
        ("remote.tv", STATE_ON, True),
        ("remote.tv", STATE_PLAYING, False),
        ("device_tracker.phone", "home", True),
        ("device_tracker.phone", "Home", True),
        ("device_tracker.phone", "HOME", True),
        ("device_tracker.phone", "not_home", False),
        ("device_tracker.phone", "work", False),
        ("device_tracker.phone", "living_room", False),
        ("sensor.arbitrary", STATE_ON, False),
        ("binary_sensor.motion", "unknown", False),
        ("binary_sensor.motion", None, False),
    ],
)
def test_presence_source_states_are_domain_specific(
    hass: HomeAssistant, entity_id, state, expected
) -> None:
    """Only states with defined semantics for the source domain are active."""
    assert is_presence_source_active(hass, entity_id, state) is expected


def test_presence_source_helper_accepts_state_objects(hass: HomeAssistant) -> None:
    """The shared evaluator accepts Home Assistant State objects."""
    state = State("media_player.tv", STATE_PLAYING)

    assert is_presence_source_active(hass, state.entity_id, state)


async def test_device_tracker_uses_only_deterministic_area_states(
    hass: HomeAssistant, freezer
) -> None:
    """A discovered tracker uses home and optional exact room states."""
    tracker_id = "device_tracker.phone"
    source_entry = MockConfigEntry(domain="test", data={})
    source_entry.add_to_hass(hass)
    async_get_entity_registry(hass).async_get_or_create(
        "device_tracker",
        "test",
        "phone",
        suggested_object_id="phone",
        config_entry=source_entry,
    )
    hass.states.async_set(tracker_id, "home")

    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    data[CONF_INCLUDE_ENTITIES] = [tracker_id]
    data[CONF_PRESENCE_DEVICE_PLATFORMS] = ["device_tracker"]
    data[CONF_CLEAR_TIMEOUT] = 1
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=data,
        version=AdaptiveConfigEntryVersion.MAJOR,
        minor_version=AdaptiveConfigEntryVersion.MINOR,
    )
    await init_integration(hass, [entry])

    area_state = hass.states.get(
        "binary_sensor.adaptive_areas_presence_tracking_kitchen_area_state"
    )
    assert area_state is not None
    assert area_state.state == STATE_ON
    assert area_state.attributes["presence_sensors"] == [tracker_id]
    assert area_state.attributes["configured_source_count"] == 1
    assert area_state.attributes["available_source_count"] == 1
    assert area_state.attributes["active_source_count"] == 1
    assert area_state.attributes["active_sources"] == [tracker_id]

    activities = []
    unsubscribe = async_dispatcher_connect(
        hass,
        AdaptiveAreasEvents.AREA_PRESENCE_ACTIVITY,
        lambda area_id, reason: activities.append((area_id, reason)),
    )

    hass.states.async_set(tracker_id, "not_home")
    await hass.async_block_till_done()
    inactive = hass.states.get(area_state.entity_id)
    assert inactive.state == STATE_ON
    assert inactive.attributes["available_source_count"] == 1
    assert inactive.attributes["active_source_count"] == 0
    assert inactive.attributes["active_sources"] == []
    assert inactive.attributes["clear_at"] is not None

    hass.states.async_set(tracker_id, "home")
    await hass.async_block_till_done()
    reactivated = hass.states.get(area_state.entity_id)
    assert reactivated.state == STATE_ON
    assert reactivated.attributes["active_sources"] == [tracker_id]
    assert reactivated.attributes["clear_at"] is None
    assert reactivated.attributes["last_activity"] is not None
    assert reactivated.attributes["last_reason"] == "presence_source_on"
    assert len(activities) == 1

    freezer.tick(1)
    previous_activity = reactivated.attributes["last_activity"]
    hass.states.async_set(tracker_id, "home")
    await hass.async_block_till_done()
    repeated = hass.states.get(area_state.entity_id)
    assert repeated.attributes["last_activity"] != previous_activity
    assert len(activities) == 2

    hass.states.async_set(tracker_id, "not_home")
    await hass.async_block_till_done()
    freezer.tick(61)
    tracker = hass.data[DATA_INSTANCES][BINARY_SENSOR_DOMAIN].get_entity(
        area_state.entity_id
    )
    tracker._update_state()
    await hass.async_block_till_done()
    assert hass.states.get(area_state.entity_id).state == STATE_OFF

    for inactive_state in ("work", "Work", "school", "unknown", "unavailable"):
        before_activity_count = len(activities)
        hass.states.async_set(tracker_id, inactive_state)
        await hass.async_block_till_done()
        inactive = hass.states.get(area_state.entity_id)
        assert inactive.state == STATE_OFF
        assert inactive.attributes["active_sources"] == []
        assert inactive.attributes["active_source_count"] == 0
        assert inactive.attributes["available_source_count"] == int(
            inactive_state not in ("unknown", "unavailable")
        )
        assert len(activities) == before_activity_count

    hass.states.async_set(tracker_id, DEFAULT_MOCK_AREA.value)
    await hass.async_block_till_done()
    active = hass.states.get(area_state.entity_id)
    assert active.state == "on"
    assert active.attributes["active_sources"] == [tracker_id]
    assert active.attributes["active_source_count"] == 1

    hass.states.async_set(tracker_id, DEFAULT_MOCK_AREA.value.title())
    await hass.async_block_till_done()
    by_name = hass.states.get(area_state.entity_id)
    assert by_name.state == "on"
    assert by_name.attributes["active_sources"] == [tracker_id]

    unsubscribe()
    await shutdown_integration(hass, [entry])


async def test_device_tracker_keep_only_cannot_initiate_presence(
    hass: HomeAssistant, entities_binary_sensor_motion_one
) -> None:
    """A home tracker in keep-only mode can hold but not start occupancy."""
    tracker_id = "device_tracker.office_pc"
    source_entry = MockConfigEntry(domain="test", data={})
    source_entry.add_to_hass(hass)
    async_get_entity_registry(hass).async_get_or_create(
        "device_tracker",
        "test",
        "office_pc",
        suggested_object_id="office_pc",
        config_entry=source_entry,
    )
    hass.states.async_set(tracker_id, "home")
    motion_id = entities_binary_sensor_motion_one[0].entity_id
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    data[CONF_INCLUDE_ENTITIES] = [tracker_id]
    data[CONF_PRESENCE_DEVICE_PLATFORMS] = ["binary_sensor", "device_tracker"]
    data[CONF_KEEP_ONLY_ENTITIES] = [tracker_id]
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    await init_integration(hass, [entry])
    area_state_id = "binary_sensor.adaptive_areas_presence_tracking_kitchen_area_state"

    assert hass.states.get(area_state_id).state == STATE_OFF
    hass.states.async_set(motion_id, STATE_ON)
    await hass.async_block_till_done()
    assert hass.states.get(area_state_id).state == STATE_ON

    hass.states.async_set(motion_id, STATE_OFF)
    await hass.async_block_till_done()
    held = hass.states.get(area_state_id)
    assert held.state == STATE_ON
    assert held.attributes["active_sources"] == [tracker_id]

    hass.states.async_set(tracker_id, "not_home")
    await hass.async_block_till_done()
    assert hass.states.get(area_state_id).state == STATE_OFF

    await shutdown_integration(hass, [entry])


async def test_device_tracker_source_activity_respects_presence_control(
    hass: HomeAssistant,
) -> None:
    """A closed confirmation gate blocks tracker occupancy and activity."""
    tracker_id = "device_tracker.office_pc"
    control_id = "person.presence_control"
    source_entry = MockConfigEntry(domain="test", data={})
    source_entry.add_to_hass(hass)
    async_get_entity_registry(hass).async_get_or_create(
        "device_tracker",
        "test",
        "office_pc",
        suggested_object_id="office_pc",
        config_entry=source_entry,
    )
    hass.states.async_set(tracker_id, "home")
    hass.states.async_set(control_id, "not_home")
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    data[CONF_INCLUDE_ENTITIES] = [tracker_id]
    data[CONF_PRESENCE_DEVICE_PLATFORMS] = ["device_tracker"]
    data[CONF_PRESENCE_CONTROL_ENTITIES] = [control_id]
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    await init_integration(hass, [entry])
    area_state_id = "binary_sensor.adaptive_areas_presence_tracking_kitchen_area_state"
    activities = []
    unsubscribe = async_dispatcher_connect(
        hass,
        AdaptiveAreasEvents.AREA_PRESENCE_ACTIVITY,
        lambda area_id, reason: activities.append((area_id, reason)),
    )

    hass.states.async_set(tracker_id, "home", {"report": 1})
    await hass.async_block_till_done()
    blocked = hass.states.get(area_state_id)
    assert blocked.state == STATE_OFF
    assert blocked.attributes["last_activity"] is None
    assert blocked.attributes["active_sources"] == []
    assert activities == []

    hass.states.async_set(control_id, "home")
    await hass.async_block_till_done()
    assert hass.states.get(area_state_id).state == STATE_ON
    assert activities == []

    hass.states.async_set(tracker_id, "home", {"report": 2})
    await hass.async_block_till_done()
    active = hass.states.get(area_state_id)
    assert active.attributes["active_sources"] == [tracker_id]
    assert active.attributes["last_activity"] is not None
    assert len(activities) == 1

    unsubscribe()
    await shutdown_integration(hass, [entry])


async def test_device_tracker_home_is_not_scanned_into_other_areas(
    hass: HomeAssistant,
) -> None:
    """A home tracker only affects Areas whose discovery selected it."""
    tracker_id = "device_tracker.office_pc"
    source_entry = MockConfigEntry(domain="test", data={})
    source_entry.add_to_hass(hass)
    async_get_entity_registry(hass).async_get_or_create(
        "device_tracker",
        "test",
        "office_pc",
        suggested_object_id="office_pc",
        config_entry=source_entry,
    )
    hass.states.async_set(tracker_id, "home")

    kitchen_data = get_basic_config_entry_data(MockAreaIds.KITCHEN)
    kitchen_data[CONF_INCLUDE_ENTITIES] = [tracker_id]
    kitchen_data[CONF_PRESENCE_DEVICE_PLATFORMS] = ["device_tracker"]
    kitchen_entry = MockConfigEntry(domain=DOMAIN, data=kitchen_data)
    living_room_data = get_basic_config_entry_data(MockAreaIds.LIVING_ROOM)
    living_room_data[CONF_PRESENCE_DEVICE_PLATFORMS] = ["device_tracker"]
    living_room_entry = MockConfigEntry(domain=DOMAIN, data=living_room_data)

    await init_integration(
        hass,
        [kitchen_entry, living_room_entry],
        areas=[MockAreaIds.KITCHEN, MockAreaIds.LIVING_ROOM],
    )

    kitchen = hass.states.get(
        "binary_sensor.adaptive_areas_presence_tracking_kitchen_area_state"
    )
    living_room = hass.states.get(
        "binary_sensor.adaptive_areas_presence_tracking_living_room_area_state"
    )
    assert kitchen.state == STATE_ON
    assert kitchen.attributes["presence_sensors"] == [tracker_id]
    assert living_room.state == STATE_OFF
    assert living_room.attributes["presence_sensors"] == []
    assert living_room.attributes["configured_source_count"] == 0

    await shutdown_integration(hass, [kitchen_entry, living_room_entry])
