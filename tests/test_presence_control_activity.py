"""Presence control gates source activity as well as occupancy."""

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.components.binary_sensor import DOMAIN as BINARY_SENSOR_DOMAIN
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import Event, HomeAssistant, State
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_component import DATA_INSTANCES

from custom_components.adaptive_areas.const import (
    CONF_CLEAR_TIMEOUT,
    CONF_PRESENCE_CONTROL_ENTITIES,
    DOMAIN,
    EVENT_ADAPTIVE_AREAS_AREA,
    AdaptiveAreasEvents,
)

from tests.const import DEFAULT_MOCK_AREA
from tests.helpers import (
    get_basic_config_entry_data,
    init_integration,
    shutdown_integration,
)

AREA_SENSOR = "binary_sensor.adaptive_areas_presence_tracking_kitchen_area_state"
CONTROL = "person.presence_control"


@pytest.fixture
async def controlled_area(hass, entities_binary_sensor_motion_one):
    """Initialize a real tracker with a closed presence gate."""
    hass.states.async_set(CONTROL, STATE_OFF)
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    data[CONF_PRESENCE_CONTROL_ENTITIES] = [CONTROL]
    data[CONF_CLEAR_TIMEOUT] = 1
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    await init_integration(hass, [entry])
    activities = []
    unsubscribe = async_dispatcher_connect(
        hass,
        AdaptiveAreasEvents.AREA_PRESENCE_ACTIVITY,
        lambda area_id, reason: activities.append((area_id, reason)),
    )
    tracker = hass.data[DATA_INSTANCES][BINARY_SENSOR_DOMAIN].get_entity(AREA_SENSOR)
    yield tracker, entities_binary_sensor_motion_one[0].entity_id, activities
    unsubscribe()
    await shutdown_integration(hass, [entry])


@pytest.mark.parametrize(
    ("control_states", "enabled"),
    [
        ([], True),
        (["on"], True),
        (["home"], True),
        (["off"], False),
        (["not_home"], False),
        (["unknown"], False),
        (["unavailable"], False),
        ([None], False),
        (["off", "on"], True),
        (["off", "off"], False),
        (["unavailable", "on"], True),
        (["unknown", "off"], False),
        ([None, "home"], True),
    ],
)
async def test_control_states_gate_activity(
    hass: HomeAssistant, controlled_area, control_states, enabled
):
    """The existing OR gate controls metadata, occupancy and activity together."""
    tracker, source, activities = controlled_area
    controls = []
    for index, state in enumerate(control_states):
        entity_id = f"binary_sensor.control_{index}"
        controls.append(entity_id)
        if state is not None:
            hass.states.async_set(entity_id, state)
    tracker._presence_control_entities = controls
    before = dict(hass.states.get(AREA_SENSOR).attributes)
    hass.states.async_set(source, STATE_ON)
    await hass.async_block_till_done()
    current = hass.states.get(AREA_SENSOR)
    assert current.state == (STATE_ON if enabled else STATE_OFF)
    assert len(activities) == int(enabled)
    assert current.attributes["active_source_count"] == int(enabled)
    assert current.attributes["active_sources"] == ([source] if enabled else [])
    if enabled:
        assert current.attributes["last_activity"] is not None
        assert current.attributes["last_reason"] == "motion_detected"
    else:
        assert current.attributes["last_activity"] == before["last_activity"]
        assert current.attributes["last_reason"] == before["last_reason"]


async def test_gate_changes_and_unchanged_reports(hass, freezer, controlled_area):
    """Gate changes reevaluate occupancy without inventing source activity."""
    _, source, activities = controlled_area
    events = []
    unsubscribe = hass.bus.async_listen(EVENT_ADAPTIVE_AREAS_AREA, events.append)
    hass.states.async_set(source, STATE_ON)
    await hass.async_block_till_done()
    before = dict(hass.states.get(AREA_SENSOR).attributes)
    freezer.tick(2)
    hass.states.async_set(source, STATE_ON)
    await hass.async_block_till_done()
    assert activities == []
    assert dict(hass.states.get(AREA_SENSOR).attributes) == before

    hass.states.async_set(CONTROL, "home")
    await hass.async_block_till_done()
    current = hass.states.get(AREA_SENSOR)
    assert current.state == STATE_ON
    assert current.attributes["active_sources"] == [source]
    assert current.attributes["last_activity"] == before["last_activity"]
    assert current.attributes["last_reason"] == "presence_control_on"
    assert activities == []
    assert [event.data["event_type"] for event in events] == ["occupied"]

    for expected in (1, 2):
        previous_activity = hass.states.get(AREA_SENSOR).attributes["last_activity"]
        freezer.tick(2)
        hass.states.async_set(source, STATE_ON)
        await hass.async_block_till_done()
        assert len(activities) == expected
        assert (
            hass.states.get(AREA_SENSOR).attributes["last_activity"]
            != previous_activity
        )
    assert [event.data["event_type"] for event in events] == ["occupied"]

    hass.states.async_set(CONTROL, STATE_OFF)
    await hass.async_block_till_done()
    current = hass.states.get(AREA_SENSOR)
    assert current.state == STATE_ON
    assert current.attributes["active_sources"] == []
    assert current.attributes["clear_at"] is not None
    before = dict(current.attributes)
    freezer.tick(2)
    hass.states.async_set(source, STATE_ON)
    await hass.async_block_till_done()
    assert dict(hass.states.get(AREA_SENSOR).attributes) == before
    assert len(activities) == 2
    unsubscribe()


async def test_blocked_motion_preserves_clear_timeout(hass, freezer, controlled_area):
    """Blocked motion cannot refresh activity or cancel an occupied area's timeout."""
    tracker, source, activities = controlled_area
    hass.states.async_set(CONTROL, STATE_ON)
    hass.states.async_set(source, STATE_ON)
    await hass.async_block_till_done()
    assert len(activities) == 1
    hass.states.async_set(source, STATE_OFF)
    await hass.async_block_till_done()
    clear_at = hass.states.get(AREA_SENSOR).attributes["clear_at"]
    assert clear_at is not None
    hass.states.async_set(CONTROL, STATE_OFF)
    await hass.async_block_till_done()
    before = dict(hass.states.get(AREA_SENSOR).attributes)
    freezer.tick(3)
    hass.states.async_set(source, STATE_ON)
    await hass.async_block_till_done()
    current = hass.states.get(AREA_SENSOR)
    assert current.state == STATE_ON
    for attribute in (
        "last_activity",
        "last_reason",
        "active_sources",
        "active_source_count",
        "clear_at",
    ):
        assert current.attributes[attribute] == before[attribute]
    assert current.attributes["clear_at"] == clear_at
    assert len(activities) == 1
    freezer.tick(61)
    tracker._update_state()
    await hass.async_block_till_done()
    assert hass.states.get(AREA_SENSOR).state == STATE_OFF
    assert len(activities) == 1


@pytest.mark.parametrize("source_state", ["off", "unknown", "unavailable"])
async def test_inactive_source_never_publishes_activity(
    hass, controlled_area, source_state
):
    """An open gate does not make inactive or invalid reports activity."""
    _, source, activities = controlled_area
    hass.states.async_set(CONTROL, STATE_ON)
    await hass.async_block_till_done()
    hass.states.async_set(source, source_state)
    await hass.async_block_till_done()
    assert activities == []
    assert hass.states.get(AREA_SENSOR).attributes["last_activity"] is None


async def test_unconfigured_source_is_not_activity(hass, controlled_area):
    """Only tracked sources may update activity metadata."""
    tracker, _, activities = controlled_area
    hass.states.async_set(CONTROL, STATE_ON)
    await hass.async_block_till_done()
    tracker._sensor_state_change(
        Event(
            "state_changed",
            {
                "entity_id": "binary_sensor.unconfigured",
                "old_state": State("binary_sensor.unconfigured", STATE_OFF),
                "new_state": State("binary_sensor.unconfigured", STATE_ON),
            },
        )
    )
    await hass.async_block_till_done()
    assert activities == []
    assert hass.states.get(AREA_SENSOR).attributes["last_activity"] is None


async def test_device_tracker_control_gates_motion_but_never_creates_presence(
    hass: HomeAssistant, entities_binary_sensor_motion_one
) -> None:
    """A phone at home confirms room activity without becoming room activity."""
    control = "device_tracker.phone"
    source = entities_binary_sensor_motion_one[0].entity_id
    hass.states.async_set(control, "home")
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    data[CONF_PRESENCE_CONTROL_ENTITIES] = [control]
    data[CONF_CLEAR_TIMEOUT] = 0
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    await init_integration(hass, [entry])

    hass.states.async_set(source, STATE_ON)
    await hass.async_block_till_done()
    assert hass.states.get(AREA_SENSOR).state == STATE_ON
    assert hass.states.get(AREA_SENSOR).attributes["active_sources"] == [source]

    hass.states.async_set(source, STATE_OFF)
    await hass.async_block_till_done()
    assert hass.states.get(AREA_SENSOR).state == STATE_OFF

    hass.states.async_set(control, "not_home")
    hass.states.async_set(source, STATE_ON)
    await hass.async_block_till_done()
    assert hass.states.get(AREA_SENSOR).state == STATE_OFF
    assert hass.states.get(AREA_SENSOR).attributes["active_sources"] == []

    hass.states.async_set(source, STATE_OFF)
    hass.states.async_set(control, "home")
    await hass.async_block_till_done()
    assert hass.states.get(AREA_SENSOR).state == STATE_OFF
    assert control not in hass.states.get(AREA_SENSOR).attributes["presence_sensors"]

    await shutdown_integration(hass, [entry])


async def test_meta_areas_do_not_publish_source_activity(
    hass,
    entities_binary_sensor_motion_all_areas_with_meta,
    _setup_integration_all_areas_with_meta,
):
    """Child occupancy propagates to meta areas without duplicating activity."""
    from tests.const import MockAreaIds

    activities = []
    unsubscribe = async_dispatcher_connect(
        hass,
        AdaptiveAreasEvents.AREA_PRESENCE_ACTIVITY,
        lambda area_id, reason: activities.append((area_id, reason)),
    )
    source = entities_binary_sensor_motion_all_areas_with_meta[MockAreaIds.KITCHEN][0]
    hass.states.async_set(source.entity_id, STATE_ON)
    await hass.async_block_till_done()
    assert activities == [(MockAreaIds.KITCHEN.value, "motion_detected")]
    meta = hass.states.get(
        "binary_sensor.adaptive_areas_presence_tracking_interior_area_state"
    )
    assert meta.state == STATE_ON
    assert meta.attributes["last_activity"] is None
    assert meta.attributes["last_reason"] == "meta_child_occupied"
    unsubscribe()
