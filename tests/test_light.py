"""Test for light groups."""

import asyncio
from collections.abc import AsyncGenerator
import logging
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.components.binary_sensor import (
    DOMAIN as BINARY_SENSOR_DOMAIN,
    BinarySensorDeviceClass,
)
from homeassistant.components.light.const import DOMAIN as LIGHT_DOMAIN
from homeassistant.components.switch.const import DOMAIN as SWITCH_DOMAIN
from homeassistant.const import ATTR_ENTITY_ID, SERVICE_TURN_ON, STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant

from custom_components.magic_areas.const import (
    CONF_ACCENT_LIGHTS,
    CONF_ACCENT_LIGHTS_ACT_ON,
    CONF_ACCENT_LIGHTS_STATES,
    CONF_DARK_ENTITY,
    CONF_ENABLED_FEATURES,
    CONF_FEATURE_LIGHT_GROUPS,
    CONF_OVERHEAD_LIGHTS,
    CONF_OVERHEAD_LIGHTS_ACT_ON,
    CONF_OVERHEAD_LIGHTS_BLOCKING_STATES,
    CONF_OVERHEAD_LIGHTS_REQUIRE_DARK,
    CONF_OVERHEAD_LIGHTS_STATES,
    CONF_OVERHEAD_LIGHTS_TURN_OFF_WHEN_BRIGHT,
    CONF_SECONDARY_STATES,
    CONF_SLEEP_ENTITY,
    DOMAIN,
    LIGHT_GROUP_ACT_ON_OPTIONS,
    LIGHT_GROUP_ACT_ON_OCCUPANCY_CHANGE,
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
from tests.mocks import MockBinarySensor, MockLight

_LOGGER = logging.getLogger(__name__)


# Fixtures


@pytest.fixture(name="light_groups_config_entry")
def mock_config_entry_light_groups() -> MockConfigEntry:
    """Fixture for mock configuration entry."""
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    data.update(
        {
            CONF_ENABLED_FEATURES: {
                CONF_FEATURE_LIGHT_GROUPS: {
                    CONF_OVERHEAD_LIGHTS: ["light.mock_light_1"],
                    CONF_OVERHEAD_LIGHTS_ACT_ON: [LIGHT_GROUP_ACT_ON_OCCUPANCY_CHANGE],
                    CONF_OVERHEAD_LIGHTS_STATES: [AreaStates.OCCUPIED],
                },
            }
        }
    )
    return MockConfigEntry(domain=DOMAIN, data=data)


@pytest.fixture(name="light_groups_multi_config_entry")
def mock_config_entry_light_groups_multiple() -> MockConfigEntry:
    """Fixture for mock configuration entry with multiple light groups."""
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    data.update(
        {
            CONF_ENABLED_FEATURES: {
                CONF_FEATURE_LIGHT_GROUPS: {
                    CONF_OVERHEAD_LIGHTS: ["light.mock_light_1"],
                    CONF_OVERHEAD_LIGHTS_ACT_ON: [LIGHT_GROUP_ACT_ON_OCCUPANCY_CHANGE],
                    CONF_OVERHEAD_LIGHTS_STATES: [AreaStates.OCCUPIED],
                    CONF_ACCENT_LIGHTS: ["light.mock_light_2"],
                    CONF_ACCENT_LIGHTS_ACT_ON: [LIGHT_GROUP_ACT_ON_OCCUPANCY_CHANGE],
                    CONF_ACCENT_LIGHTS_STATES: [AreaStates.OCCUPIED],
                },
            }
        }
    )
    return MockConfigEntry(domain=DOMAIN, data=data)


@pytest.fixture(name="light_groups_advanced_config_entry")
def mock_config_entry_light_groups_advanced() -> MockConfigEntry:
    """Fixture for mock configuration entry with blocking and bright-off options."""
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    options = {
        CONF_SECONDARY_STATES: {
            CONF_SLEEP_ENTITY: "binary_sensor.sleep_sensor",
            CONF_DARK_ENTITY: "binary_sensor.light_level_sensor",
        },
        CONF_ENABLED_FEATURES: {
            CONF_FEATURE_LIGHT_GROUPS: {
                CONF_OVERHEAD_LIGHTS: ["light.mock_light_1"],
                CONF_OVERHEAD_LIGHTS_ACT_ON: LIGHT_GROUP_ACT_ON_OPTIONS,
                CONF_OVERHEAD_LIGHTS_STATES: [AreaStates.OCCUPIED],
                CONF_OVERHEAD_LIGHTS_BLOCKING_STATES: [AreaStates.SLEEP],
                CONF_OVERHEAD_LIGHTS_TURN_OFF_WHEN_BRIGHT: True,
            },
        },
    }
    return MockConfigEntry(
        domain=DOMAIN,
        data=data,
        options=options,
    )


@pytest.fixture(name="light_groups_bright_config_entry")
def mock_config_entry_light_groups_bright() -> MockConfigEntry:
    """Fixture for mock configuration entry with a dark sensor but no bright turn-off."""
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    options = {
        CONF_SECONDARY_STATES: {
            CONF_DARK_ENTITY: "binary_sensor.light_level_sensor",
        },
        CONF_ENABLED_FEATURES: {
            CONF_FEATURE_LIGHT_GROUPS: {
                CONF_OVERHEAD_LIGHTS: ["light.mock_light_1"],
                CONF_OVERHEAD_LIGHTS_ACT_ON: LIGHT_GROUP_ACT_ON_OPTIONS,
                CONF_OVERHEAD_LIGHTS_STATES: [AreaStates.OCCUPIED],
            },
        },
    }
    return MockConfigEntry(
        domain=DOMAIN,
        data=data,
        options=options,
    )


@pytest.fixture(name="_setup_integration_light_groups")
async def setup_integration_light_groups(
    hass: HomeAssistant,
    light_groups_config_entry: MockConfigEntry,
) -> AsyncGenerator[Any]:
    """Set up integration with BLE tracker config."""

    await init_integration(hass, [light_groups_config_entry])
    yield
    await shutdown_integration(hass, [light_groups_config_entry])


@pytest.fixture(name="_setup_integration_light_groups_multiple")
async def setup_integration_light_groups_multiple(
    hass: HomeAssistant,
    light_groups_multi_config_entry: MockConfigEntry,
) -> AsyncGenerator[Any]:
    """Set up integration with multiple light groups config."""
    await init_integration(hass, [light_groups_multi_config_entry])
    yield
    await shutdown_integration(hass, [light_groups_multi_config_entry])


@pytest.fixture(name="_setup_integration_light_groups_advanced")
async def setup_integration_light_groups_advanced(
    hass: HomeAssistant,
    light_groups_advanced_config_entry: MockConfigEntry,
) -> AsyncGenerator[Any]:
    """Set up integration with advanced light-group options."""

    await init_integration(hass, [light_groups_advanced_config_entry])
    yield
    await shutdown_integration(hass, [light_groups_advanced_config_entry])


@pytest.fixture(name="_setup_integration_light_groups_bright")
async def setup_integration_light_groups_bright(
    hass: HomeAssistant,
    light_groups_bright_config_entry: MockConfigEntry,
) -> AsyncGenerator[Any]:
    """Set up integration with bright transitions and default light behavior."""

    await init_integration(hass, [light_groups_bright_config_entry])
    yield
    await shutdown_integration(hass, [light_groups_bright_config_entry])


# Entities


@pytest.fixture(name="entities_light_one")
async def setup_entities_light_one(
    hass: HomeAssistant,
) -> list[MockLight]:
    """Create one mock light and setup the system with it."""
    mock_light_entities = [
        MockLight(
            name="mock_light_1",
            state="off",
            unique_id="unique_light",
        )
    ]
    await setup_mock_entities(
        hass, LIGHT_DOMAIN, {DEFAULT_MOCK_AREA: mock_light_entities}
    )
    return mock_light_entities


@pytest.fixture(name="entities_light_two")
async def setup_entities_light_two(
    hass: HomeAssistant,
) -> list[MockLight]:
    """Create two mock lights and setup the system with them."""
    mock_light_entities = [
        MockLight(
            name="mock_light_1",
            state="off",
            unique_id="unique_light_1",
        ),
        MockLight(
            name="mock_light_2",
            state="off",
            unique_id="unique_light_2",
        ),
    ]
    await setup_mock_entities(
        hass, LIGHT_DOMAIN, {DEFAULT_MOCK_AREA: mock_light_entities}
    )
    return mock_light_entities


@pytest.fixture(name="entities_light_secondary_states")
async def setup_entities_light_secondary_states(
    hass: HomeAssistant,
) -> list[MockBinarySensor]:
    """Create sleep and light-level entities for secondary state testing."""
    mock_binary_sensor_entities = [
        MockBinarySensor(
            name="sleep_sensor",
            state="off",
            unique_id="unique_sleep",
            device_class=BinarySensorDeviceClass.OCCUPANCY,
        ),
        MockBinarySensor(
            name="light_level_sensor",
            state="off",
            unique_id="unique_light_level",
            device_class=BinarySensorDeviceClass.LIGHT,
        ),
    ]
    await setup_mock_entities(
        hass,
        BINARY_SENSOR_DOMAIN,
        {DEFAULT_MOCK_AREA: mock_binary_sensor_entities},
    )
    return mock_binary_sensor_entities


# Tests


async def test_light_group_basic(
    hass: HomeAssistant,
    entities_light_one: list[MockLight],
    entities_binary_sensor_motion_one: list[MockBinarySensor],
    _setup_integration_light_groups,
) -> None:
    """Test light group."""

    mock_light_entity_id = entities_light_one[0].entity_id
    mock_motion_sensor_entity_id = entities_binary_sensor_motion_one[0].entity_id
    light_group_entity_id = (
        f"{LIGHT_DOMAIN}.magic_areas_light_groups_{DEFAULT_MOCK_AREA}_overhead_lights"
    )
    light_control_entity_id = (
        f"{SWITCH_DOMAIN}.magic_areas_light_groups_{DEFAULT_MOCK_AREA}_light_control"
    )
    area_sensor_entity_id = f"{BINARY_SENSOR_DOMAIN}.magic_areas_presence_tracking_{DEFAULT_MOCK_AREA}_area_state"

    # Test mock entity created
    mock_light_state = hass.states.get(mock_light_entity_id)
    assert_state(mock_light_state, STATE_OFF)

    # Test light group created
    light_group_state = hass.states.get(light_group_entity_id)
    assert_state(light_group_state, STATE_OFF)
    assert_in_attribute(light_group_state, ATTR_ENTITY_ID, mock_light_entity_id)

    # Test light control switch created
    light_control_state = hass.states.get(light_control_entity_id)
    assert_state(light_control_state, STATE_OFF)

    # Test motion sensor created
    motion_sensor_state = hass.states.get(mock_motion_sensor_entity_id)
    assert_state(motion_sensor_state, STATE_OFF)

    # Test area state
    area_state = hass.states.get(area_sensor_entity_id)
    assert_state(area_state, STATE_OFF)

    # Turn on light control
    hass.states.async_set(light_control_entity_id, STATE_ON)
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: light_control_entity_id}
    )
    await hass.async_block_till_done()

    # Test light control switch state turned on
    light_control_state = hass.states.get(light_control_entity_id)
    assert_state(light_control_state, STATE_ON)

    # Turn motion sensor on
    hass.states.async_set(mock_motion_sensor_entity_id, STATE_ON)
    await hass.async_block_till_done()

    motion_sensor_state = hass.states.get(mock_motion_sensor_entity_id)
    assert_state(motion_sensor_state, STATE_ON)

    # Test area state is STATE_ON
    area_state = hass.states.get(area_sensor_entity_id)
    assert_state(area_state, STATE_ON)

    await asyncio.sleep(1)

    # Check light group is on
    light_group_state = hass.states.get(light_group_entity_id)
    assert_state(light_group_state, STATE_ON)

    # Turn motion sensor off
    hass.states.async_set(mock_motion_sensor_entity_id, STATE_OFF)
    await hass.async_block_till_done()

    # Test area state is STATE_OFF
    area_state = hass.states.get(area_sensor_entity_id)
    assert_state(area_state, STATE_OFF)

    # Check light group is off
    light_group_state = hass.states.get(light_group_entity_id)
    assert_state(light_group_state, STATE_OFF)


async def test_light_group_blocking_state_turns_off(
    hass: HomeAssistant,
    entities_light_one: list[MockLight],
    entities_binary_sensor_motion_one: list[MockBinarySensor],
    entities_light_secondary_states: list[MockBinarySensor],
    _setup_integration_light_groups_advanced,
) -> None:
    """Test that a configured blocking state turns a group off."""
    light_group_entity_id = (
        f"{LIGHT_DOMAIN}.magic_areas_light_groups_{DEFAULT_MOCK_AREA}_overhead_lights"
    )
    light_control_entity_id = (
        f"{SWITCH_DOMAIN}.magic_areas_light_groups_{DEFAULT_MOCK_AREA}_light_control"
    )

    motion_sensor_entity_id = entities_binary_sensor_motion_one[0].entity_id
    sleep_sensor_entity_id = entities_light_secondary_states[0].entity_id

    hass.states.async_set(light_control_entity_id, STATE_ON)
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: light_control_entity_id}
    )
    await hass.async_block_till_done()

    hass.states.async_set(motion_sensor_entity_id, STATE_ON)
    await hass.async_block_till_done()
    await asyncio.sleep(1)

    light_group_state = hass.states.get(light_group_entity_id)
    assert_state(light_group_state, STATE_ON)

    hass.states.async_set(sleep_sensor_entity_id, STATE_ON)
    await hass.async_block_till_done()
    await asyncio.sleep(1)

    light_group_state = hass.states.get(light_group_entity_id)
    assert_state(light_group_state, STATE_OFF)


async def test_light_group_turns_off_when_bright(
    hass: HomeAssistant,
    entities_light_one: list[MockLight],
    entities_binary_sensor_motion_one: list[MockBinarySensor],
    entities_light_secondary_states: list[MockBinarySensor],
    _setup_integration_light_groups_advanced,
) -> None:
    """Test that turn_off_when_bright actively turns lights off."""
    light_group_entity_id = (
        f"{LIGHT_DOMAIN}.magic_areas_light_groups_{DEFAULT_MOCK_AREA}_overhead_lights"
    )
    light_control_entity_id = (
        f"{SWITCH_DOMAIN}.magic_areas_light_groups_{DEFAULT_MOCK_AREA}_light_control"
    )

    motion_sensor_entity_id = entities_binary_sensor_motion_one[0].entity_id
    sleep_sensor_entity_id = entities_light_secondary_states[0].entity_id
    light_level_entity_id = entities_light_secondary_states[1].entity_id

    hass.states.async_set(light_control_entity_id, STATE_ON)
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: light_control_entity_id}
    )
    await hass.async_block_till_done()

    # Keep area dark so lights can turn on.
    hass.states.async_set(light_level_entity_id, STATE_OFF)
    hass.states.async_set(sleep_sensor_entity_id, STATE_OFF)
    hass.states.async_set(motion_sensor_entity_id, STATE_ON)
    await hass.async_block_till_done()
    await asyncio.sleep(1)

    light_group_state = hass.states.get(light_group_entity_id)
    assert_state(light_group_state, STATE_ON)

    # Bright transition should actively turn off the group.
    hass.states.async_set(light_level_entity_id, STATE_ON)
    await hass.async_block_till_done()
    await asyncio.sleep(1)

    light_group_state = hass.states.get(light_group_entity_id)
    assert_state(light_group_state, STATE_OFF)


async def test_light_group_turns_back_on_when_dark_again(
    hass: HomeAssistant,
    entities_light_one: list[MockLight],
    entities_binary_sensor_motion_one: list[MockBinarySensor],
    entities_light_secondary_states: list[MockBinarySensor],
    _setup_integration_light_groups_advanced,
) -> None:
    """Test lights recover when transitioning from bright back to dark."""
    light_group_entity_id = (
        f"{LIGHT_DOMAIN}.magic_areas_light_groups_{DEFAULT_MOCK_AREA}_overhead_lights"
    )
    light_control_entity_id = (
        f"{SWITCH_DOMAIN}.magic_areas_light_groups_{DEFAULT_MOCK_AREA}_light_control"
    )

    motion_sensor_entity_id = entities_binary_sensor_motion_one[0].entity_id
    light_level_entity_id = entities_light_secondary_states[1].entity_id

    hass.states.async_set(light_control_entity_id, STATE_ON)
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: light_control_entity_id}
    )
    await hass.async_block_till_done()

    # Occupied + dark -> lights on.
    hass.states.async_set(light_level_entity_id, STATE_OFF)
    hass.states.async_set(motion_sensor_entity_id, STATE_ON)
    await hass.async_block_till_done()
    await asyncio.sleep(1)

    light_group_state = hass.states.get(light_group_entity_id)
    assert_state(light_group_state, STATE_ON)

    # Bright -> lights off (configured behavior).
    hass.states.async_set(light_level_entity_id, STATE_ON)
    await hass.async_block_till_done()
    await asyncio.sleep(1)

    light_group_state = hass.states.get(light_group_entity_id)
    assert_state(light_group_state, STATE_OFF)

    # Dark again while still occupied -> lights should turn back on and stay on.
    hass.states.async_set(light_level_entity_id, STATE_OFF)
    await hass.async_block_till_done()
    await asyncio.sleep(1)

    light_group_state = hass.states.get(light_group_entity_id)
    assert_state(light_group_state, STATE_ON)


async def test_light_group_stays_on_when_bright_if_not_configured(
    hass: HomeAssistant,
    entities_light_one: list[MockLight],
    entities_binary_sensor_motion_one: list[MockBinarySensor],
    entities_light_secondary_states: list[MockBinarySensor],
    _setup_integration_light_groups_bright,
) -> None:
    """Test bright transitions do not turn off lights unless configured."""
    light_group_entity_id = (
        f"{LIGHT_DOMAIN}.magic_areas_light_groups_{DEFAULT_MOCK_AREA}_overhead_lights"
    )
    light_control_entity_id = (
        f"{SWITCH_DOMAIN}.magic_areas_light_groups_{DEFAULT_MOCK_AREA}_light_control"
    )

    motion_sensor_entity_id = entities_binary_sensor_motion_one[0].entity_id
    light_level_entity_id = entities_light_secondary_states[1].entity_id

    hass.states.async_set(light_control_entity_id, STATE_ON)
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: light_control_entity_id}
    )
    await hass.async_block_till_done()

    # Ensure occupied and dark first.
    hass.states.async_set(light_level_entity_id, STATE_OFF)
    hass.states.async_set(motion_sensor_entity_id, STATE_ON)
    await hass.async_block_till_done()
    await asyncio.sleep(1)

    light_group_state = hass.states.get(light_group_entity_id)
    assert_state(light_group_state, STATE_ON)

    # Bright transition should not turn off without turn_off_when_bright enabled.
    hass.states.async_set(light_level_entity_id, STATE_ON)
    await hass.async_block_till_done()
    await asyncio.sleep(1)

    light_group_state = hass.states.get(light_group_entity_id)
    assert_state(light_group_state, STATE_ON)


async def test_light_group_does_not_turn_on_when_occupied_and_bright(
    hass: HomeAssistant,
    entities_light_one: list[MockLight],
    entities_binary_sensor_motion_one: list[MockBinarySensor],
    entities_light_secondary_states: list[MockBinarySensor],
    _setup_integration_light_groups_bright,
) -> None:
    """Test darkness-required groups stay off when startup state is bright."""
    light_group_entity_id = (
        f"{LIGHT_DOMAIN}.magic_areas_light_groups_{DEFAULT_MOCK_AREA}_overhead_lights"
    )
    light_control_entity_id = (
        f"{SWITCH_DOMAIN}.magic_areas_light_groups_{DEFAULT_MOCK_AREA}_light_control"
    )

    motion_sensor_entity_id = entities_binary_sensor_motion_one[0].entity_id
    light_level_entity_id = entities_light_secondary_states[1].entity_id

    hass.states.async_set(light_control_entity_id, STATE_ON)
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: light_control_entity_id}
    )
    await hass.async_block_till_done()

    # Reproduce startup ordering: brightness is known before occupancy is restored.
    hass.states.async_set(light_level_entity_id, STATE_ON)
    await hass.async_block_till_done()
    hass.states.async_set(motion_sensor_entity_id, STATE_ON)
    await hass.async_block_till_done()
    await asyncio.sleep(1)

    light_group_state = hass.states.get(light_group_entity_id)
    assert_state(light_group_state, STATE_OFF)


async def test_light_group_can_turn_on_when_bright_if_darkness_not_required(
    hass: HomeAssistant,
    entities_light_one: list[MockLight],
    entities_binary_sensor_motion_one: list[MockBinarySensor],
    entities_light_secondary_states: list[MockBinarySensor],
    light_groups_bright_config_entry: MockConfigEntry,
) -> None:
    """Test darkness requirement can be disabled per group."""
    light_groups_bright_config_entry.options[CONF_ENABLED_FEATURES][
        CONF_FEATURE_LIGHT_GROUPS
    ][CONF_OVERHEAD_LIGHTS_REQUIRE_DARK] = False
    await init_integration(hass, [light_groups_bright_config_entry])

    light_group_entity_id = (
        f"{LIGHT_DOMAIN}.magic_areas_light_groups_{DEFAULT_MOCK_AREA}_overhead_lights"
    )
    light_control_entity_id = (
        f"{SWITCH_DOMAIN}.magic_areas_light_groups_{DEFAULT_MOCK_AREA}_light_control"
    )
    motion_sensor_entity_id = entities_binary_sensor_motion_one[0].entity_id
    light_level_entity_id = entities_light_secondary_states[1].entity_id

    hass.states.async_set(light_control_entity_id, STATE_ON)
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: light_control_entity_id}
    )
    hass.states.async_set(light_level_entity_id, STATE_ON)
    await hass.async_block_till_done()
    hass.states.async_set(motion_sensor_entity_id, STATE_ON)
    await hass.async_block_till_done()
    await asyncio.sleep(1)

    light_group_state = hass.states.get(light_group_entity_id)
    assert_state(light_group_state, STATE_ON)
    await shutdown_integration(hass, [light_groups_bright_config_entry])


async def test_light_group_all_contains_valid_child_ids_for_multiple_groups(
    hass: HomeAssistant,
    entities_light_two: list[MockLight],
    _setup_integration_light_groups_multiple,
) -> None:
    """Test all_lights group exposes valid child IDs when multiple groups exist."""
    del entities_light_two

    all_lights_group_entity_id = (
        f"{LIGHT_DOMAIN}.magic_areas_light_groups_{DEFAULT_MOCK_AREA}_all_lights"
    )
    overhead_group_entity_id = (
        f"{LIGHT_DOMAIN}.magic_areas_light_groups_{DEFAULT_MOCK_AREA}_overhead_lights"
    )
    accent_group_entity_id = (
        f"{LIGHT_DOMAIN}.magic_areas_light_groups_{DEFAULT_MOCK_AREA}_accent_lights"
    )

    all_lights_group_state = hass.states.get(all_lights_group_entity_id)
    assert all_lights_group_state is not None

    child_ids = all_lights_group_state.attributes["child_ids"]
    assert overhead_group_entity_id in child_ids
    assert accent_group_entity_id in child_ids
