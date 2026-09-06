"""Test for area changes and how the system handles it."""

from collections.abc import AsyncGenerator
import logging
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.components.binary_sensor import (
    DOMAIN as BINARY_SENSOR_DOMAIN,
    BinarySensorDeviceClass,
)
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_component import DATA_INSTANCES

from custom_components.adaptive_areas.const import (
    ATTR_PRESENCE_SENSORS,
    ATTR_STATES,
    CONF_ACCENT_ENTITY,
    CONF_CLEAR_TIMEOUT,
    CONF_DARK_ENTITY,
    CONF_EXTENDED_TIME,
    CONF_KEEP_ONLY_ENTITIES,
    CONF_SECONDARY_STATES,
    CONF_SLEEP_ENTITY,
    DATA_AREA_OBJECT,
    DOMAIN,
    EVENT_ADAPTIVE_AREAS_AREA,
    MODULE_DATA,
    AreaStates,
)

from tests.const import DEFAULT_MOCK_AREA
from tests.helpers import (
    assert_in_attribute,
    assert_state,
    get_basic_config_entry_data,
    init_integration,
    setup_mock_entities,
    shutdown_integration,
)
from tests.mocks import MockBinarySensor

_LOGGER = logging.getLogger(__name__)


# Fixtures


@pytest.fixture(name="secondary_states_config_entry")
def mock_config_entry_secondary_states() -> MockConfigEntry:
    """Fixture for mock configuration entry."""
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    data.update(
        {
            CONF_SECONDARY_STATES: {
                CONF_ACCENT_ENTITY: "binary_sensor.accent_sensor",
                CONF_DARK_ENTITY: "binary_sensor.area_light_sensor",
                CONF_SLEEP_ENTITY: "binary_sensor.sleep_sensor",
            }
        }
    )
    return MockConfigEntry(domain=DOMAIN, data=data)


@pytest.fixture(name="keep_only_sensor_config_entry")
def mock_config_entry_keep_only_sensor() -> MockConfigEntry:
    """Fixture for mock configuration entry."""
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    data.update({CONF_KEEP_ONLY_ENTITIES: ["binary_sensor.motion_sensor_1"]})
    return MockConfigEntry(domain=DOMAIN, data=data)


@pytest.fixture(name="_setup_integration_secondary_states")
async def setup_integration_secondary_states(
    hass: HomeAssistant,
    secondary_states_config_entry: MockConfigEntry,
) -> AsyncGenerator[Any]:
    """Set up integration with secondary states config."""

    await init_integration(hass, [secondary_states_config_entry])
    yield
    await shutdown_integration(hass, [secondary_states_config_entry])


@pytest.fixture(name="_setup_integration_keep_only_sensor")
async def setup_integration_keep_only_sensor(
    hass: HomeAssistant,
    keep_only_sensor_config_entry: MockConfigEntry,
) -> AsyncGenerator[Any]:
    """Set up integration with secondary states config."""

    await init_integration(hass, [keep_only_sensor_config_entry])
    yield
    await shutdown_integration(hass, [keep_only_sensor_config_entry])


# Entities


@pytest.fixture(name="secondary_states_sensors")
async def setup_secondary_state_sensors(hass: HomeAssistant) -> list[MockBinarySensor]:
    """Create binary sensors for the secondary states."""
    mock_binary_sensor_entities = [
        MockBinarySensor(
            name="sleep_sensor",
            unique_id="sleep_sensor",
            device_class=None,
        ),
        MockBinarySensor(
            name="area_light_sensor",
            unique_id="area_light_sensor",
            device_class=BinarySensorDeviceClass.LIGHT,
        ),
        MockBinarySensor(
            name="accent_sensor",
            unique_id="accent_sensor",
            device_class=None,
        ),
    ]
    await setup_mock_entities(
        hass, BINARY_SENSOR_DOMAIN, {DEFAULT_MOCK_AREA: mock_binary_sensor_entities}
    )
    return mock_binary_sensor_entities


# Tests


async def test_area_primary_state_change(
    hass: HomeAssistant,
    basic_config_entry: MockConfigEntry,
    entities_binary_sensor_motion_one: list[MockBinarySensor],
    _setup_integration_basic,
) -> None:
    """Test primary area state change."""

    motion_sensor_entity_id = entities_binary_sensor_motion_one[0].entity_id
    area_sensor_entity_id = (
        f"{BINARY_SENSOR_DOMAIN}.adaptive_areas_presence_tracking_kitchen_area_state"
    )

    # Validate the right enties were created.
    area_binary_sensor = hass.states.get(area_sensor_entity_id)
    assert_state(area_binary_sensor, STATE_OFF)
    assert_in_attribute(
        area_binary_sensor, ATTR_PRESENCE_SENSORS, motion_sensor_entity_id
    )
    assert_in_attribute(area_binary_sensor, ATTR_STATES, AreaStates.CLEAR)

    # Turn on motion sensor
    hass.states.async_set(motion_sensor_entity_id, STATE_ON)
    await hass.async_block_till_done()

    # Update states
    area_binary_sensor = hass.states.get(area_sensor_entity_id)
    motion_sensor = hass.states.get(motion_sensor_entity_id)
    assert_state(motion_sensor, STATE_ON)
    assert_state(area_binary_sensor, STATE_ON)
    assert_in_attribute(area_binary_sensor, ATTR_STATES, AreaStates.OCCUPIED)
    area = hass.data[MODULE_DATA][basic_config_entry.entry_id][DATA_AREA_OBJECT]
    assert any(
        entry["feature"] == "presence"
        and entry["to"] == AreaStates.OCCUPIED
        and "presence_detected" in entry["reason_codes"]
        for entry in area.decision_trace.export()
    )

    # Turn off motion sensor
    hass.states.async_set(motion_sensor_entity_id, STATE_OFF)
    await hass.async_block_till_done()

    # @FIXME figure out why this is blocking instead of doing the VirtualClock trick
    # await asyncio.sleep(60)
    # await hass.async_block_till_done()

    # Update states
    area_binary_sensor = hass.states.get(area_sensor_entity_id)
    motion_sensor = hass.states.get(motion_sensor_entity_id)
    assert_state(motion_sensor, STATE_OFF)
    assert_state(area_binary_sensor, STATE_OFF)
    assert_in_attribute(area_binary_sensor, ATTR_STATES, AreaStates.CLEAR)

    assert any(
        entry["feature"] == "presence"
        and entry["to"] == AreaStates.CLEAR
        and "presence_cleared" in entry["reason_codes"]
        for entry in area.decision_trace.export()
    )


async def test_area_secondary_state_change(
    hass: HomeAssistant,
    secondary_states_sensors: list[MockBinarySensor],
    _setup_integration_secondary_states,
) -> None:
    """Test secondary area state changes."""

    area_sensor_entity_id = (
        f"{BINARY_SENSOR_DOMAIN}.adaptive_areas_presence_tracking_kitchen_area_state"
    )

    secondary_state_map = {
        secondary_states_sensors[0].entity_id: (AreaStates.SLEEP, None),
        secondary_states_sensors[1].entity_id: (AreaStates.BRIGHT, AreaStates.DARK),
        secondary_states_sensors[2].entity_id: (AreaStates.ACCENT, None),
    }

    for entity_id, state_tuples in secondary_state_map.items():
        area_binary_sensor = hass.states.get(area_sensor_entity_id)
        entity_state = hass.states.get(entity_id)

        # Ensure off
        assert_state(entity_state, STATE_OFF)
        assert_in_attribute(
            area_binary_sensor, ATTR_STATES, state_tuples[0], negate=True
        )
        if state_tuples[1]:
            assert_in_attribute(area_binary_sensor, ATTR_STATES, state_tuples[1])

        # Turn entity on
        hass.states.async_set(entity_id, STATE_ON)
        await hass.async_block_till_done()

        # Update states
        area_binary_sensor = hass.states.get(area_sensor_entity_id)
        entity_state = hass.states.get(entity_id)

        # Ensure on
        assert_state(entity_state, STATE_ON)
        assert_in_attribute(area_binary_sensor, ATTR_STATES, state_tuples[0])
        if state_tuples[1]:
            assert_in_attribute(
                area_binary_sensor, ATTR_STATES, state_tuples[1], negate=True
            )

        # Turn entity off
        hass.states.async_set(entity_id, STATE_OFF)
        await hass.async_block_till_done()

        # Update states
        area_binary_sensor = hass.states.get(area_sensor_entity_id)
        entity_state = hass.states.get(entity_id)

        # Ensure off
        assert_state(entity_state, STATE_OFF)
        assert_in_attribute(
            area_binary_sensor, ATTR_STATES, state_tuples[0], negate=True
        )
        if state_tuples[1]:
            assert_in_attribute(area_binary_sensor, ATTR_STATES, state_tuples[1])


# Test extended state
# @TODO pending figuring out virtualclock


# Test keep-only sensors
async def test_keep_only_sensors(
    hass: HomeAssistant,
    entities_binary_sensor_motion_multiple: list[MockBinarySensor],
    _setup_integration_keep_only_sensor,
) -> None:
    """Test keep-only sensors."""

    motion_sensor_entity_id = entities_binary_sensor_motion_multiple[0].entity_id
    flappy_sensor_entity_id = entities_binary_sensor_motion_multiple[1].entity_id
    area_sensor_entity_id = (
        f"{BINARY_SENSOR_DOMAIN}.adaptive_areas_presence_tracking_kitchen_area_state"
    )

    # Validate the right enties were created.
    area_binary_sensor = hass.states.get(area_sensor_entity_id)

    assert_state(area_binary_sensor, STATE_OFF)
    assert_in_attribute(
        area_binary_sensor, ATTR_PRESENCE_SENSORS, motion_sensor_entity_id
    )
    assert_in_attribute(
        area_binary_sensor, ATTR_PRESENCE_SENSORS, flappy_sensor_entity_id
    )
    assert_in_attribute(area_binary_sensor, ATTR_STATES, AreaStates.CLEAR)

    # A keep-only sensor cannot initiate occupancy.
    hass.states.async_set(flappy_sensor_entity_id, STATE_ON)
    await hass.async_block_till_done()
    assert_state(hass.states.get(area_sensor_entity_id), STATE_OFF)

    # It does keep an Area occupied after a normal source initiated presence.
    hass.states.async_set(motion_sensor_entity_id, STATE_ON)
    await hass.async_block_till_done()
    assert_state(hass.states.get(area_sensor_entity_id), STATE_ON)
    hass.states.async_set(motion_sensor_entity_id, STATE_OFF)
    await hass.async_block_till_done()
    assert_state(hass.states.get(area_sensor_entity_id), STATE_ON)
    hass.states.async_set(flappy_sensor_entity_id, STATE_OFF)
    await hass.async_block_till_done()
    assert_state(hass.states.get(area_sensor_entity_id), STATE_OFF)


async def test_presence_explanation_timing_counts_and_events(
    hass: HomeAssistant,
    freezer,
    basic_config_entry: MockConfigEntry,
    entities_binary_sensor_motion_one: list[MockBinarySensor],
    _setup_integration_basic,
) -> None:
    """The existing presence entity explains real transitions without polling noise."""
    entity_id = (
        f"{BINARY_SENSOR_DOMAIN}.adaptive_areas_presence_tracking_kitchen_area_state"
    )
    source_id = entities_binary_sensor_motion_one[0].entity_id
    events = []
    hass.bus.async_listen(EVENT_ADAPTIVE_AREAS_AREA, events.append)

    initial = hass.states.get(entity_id)
    assert initial is not None
    assert initial.attributes["configured_source_count"] == 1
    assert initial.attributes["available_source_count"] == 1
    assert initial.attributes["active_source_count"] == 0
    assert initial.attributes["occupied_since"] is None

    for unavailable_state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
        hass.states.async_set(source_id, unavailable_state)
        await hass.async_block_till_done()
        assert hass.states.get(entity_id).attributes["available_source_count"] == 0
    hass.states.async_set(source_id, STATE_OFF)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).attributes["available_source_count"] == 1

    hass.states.async_set(source_id, STATE_ON)
    await hass.async_block_till_done()
    occupied = hass.states.get(entity_id)
    occupied_since = occupied.attributes["occupied_since"]
    first_activity = occupied.attributes["last_activity"]
    assert occupied_since is not None
    assert first_activity is not None
    assert occupied.attributes["active_source_count"] == 1
    assert occupied.attributes["active_sources"] == [source_id]
    assert occupied.attributes["last_reason"] == "motion_detected"

    component = hass.data[DATA_INSTANCES][BINARY_SENSOR_DOMAIN]
    tracker = component.get_entity(entity_id)
    freezer.tick(10)
    tracker._update_state()
    unchanged = hass.states.get(entity_id)
    assert unchanged.attributes["occupied_since"] == occupied_since
    assert unchanged.attributes["last_activity"] == first_activity

    freezer.tick(10)
    hass.states.async_set(source_id, STATE_ON, {"activity": "new"})
    await hass.async_block_till_done()
    repeated = hass.states.get(entity_id)
    assert repeated.attributes["occupied_since"] == occupied_since
    assert repeated.attributes["last_activity"] != first_activity

    area = hass.data[MODULE_DATA][basic_config_entry.entry_id][DATA_AREA_OBJECT]
    area.config[CONF_CLEAR_TIMEOUT] = 1
    hass.states.async_set(source_id, STATE_OFF)
    await hass.async_block_till_done()
    pending = hass.states.get(entity_id)
    assert pending.state == STATE_ON
    assert pending.attributes["clear_at"] is not None

    hass.states.async_set(source_id, STATE_ON)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).attributes["clear_at"] is None
    hass.states.async_set(source_id, STATE_OFF)
    await hass.async_block_till_done()
    freezer.tick(61)
    tracker._update_state()
    cleared = hass.states.get(entity_id)
    assert cleared.attributes["occupied_since"] is None
    assert cleared.attributes["last_cleared"] is not None
    assert cleared.attributes["clear_at"] is None
    assert [event.data["event_type"] for event in events] == ["occupied", "cleared"]
    assert all(
        event.data["area_id"] == basic_config_entry.data["id"] for event in events
    )


async def test_secondary_state_semantic_events_are_transition_only(
    hass: HomeAssistant,
    secondary_states_sensors: list[MockBinarySensor],
    _setup_integration_secondary_states,
) -> None:
    """Secondary state starts and ends publish deterministic public events once."""
    events = []
    hass.bus.async_listen(EVENT_ADAPTIVE_AREAS_AREA, events.append)
    expected = {
        secondary_states_sensors[0].entity_id: ("sleep_started", "sleep_ended"),
        secondary_states_sensors[1].entity_id: ("dark_ended", "dark_started"),
        secondary_states_sensors[2].entity_id: ("accented_started", "accented_ended"),
    }
    for source_id, event_types in expected.items():
        hass.states.async_set(source_id, STATE_ON)
        await hass.async_block_till_done()
        hass.states.async_set(source_id, STATE_ON)
        await hass.async_block_till_done()
        hass.states.async_set(source_id, STATE_OFF)
        await hass.async_block_till_done()
        assert [event.data["event_type"] for event in events[-2:]] == list(event_types)


async def test_extended_semantic_events(
    hass: HomeAssistant,
    entities_binary_sensor_motion_one: list[MockBinarySensor],
    basic_config_entry: MockConfigEntry,
    _setup_integration_basic,
) -> None:
    """Extended state start and end are exposed without an event entity."""
    area = hass.data[MODULE_DATA][basic_config_entry.entry_id][DATA_AREA_OBJECT]
    area.config.setdefault(CONF_SECONDARY_STATES, {})[CONF_EXTENDED_TIME] = 0
    events = []
    hass.bus.async_listen(EVENT_ADAPTIVE_AREAS_AREA, events.append)
    source_id = entities_binary_sensor_motion_one[0].entity_id
    hass.states.async_set(source_id, STATE_ON)
    await hass.async_block_till_done()
    entity_id = (
        f"{BINARY_SENSOR_DOMAIN}.adaptive_areas_presence_tracking_kitchen_area_state"
    )
    tracker = hass.data[DATA_INSTANCES][BINARY_SENSOR_DOMAIN].get_entity(entity_id)
    previous_states = set(area.states)
    tracker._update_explanation(
        previous_states,
        previous_states - {AreaStates.EXTENDED},
        (set(), {AreaStates.EXTENDED}),
    )
    event_types = [event.data["event_type"] for event in events]
    assert "extended_started" in event_types
    assert "extended_ended" in event_types
