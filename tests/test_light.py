"""Test for light groups."""

from collections.abc import AsyncGenerator
import logging
from typing import Any

from unittest.mock import patch

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

from custom_components.adaptive_areas.const import (
    CONF_FEATURE_LIGHT,
    CONF_GLOBAL_LIGHT_SENSOR,
    CONF_GLOBAL_OPTIONS,
    CONF_ACCENT_LIGHTS,
    CONF_ACCENT_LIGHTS_ACT_ON,
    CONF_ACCENT_LIGHTS_STATES,
    CONF_ENABLED_FEATURES,
    CONF_FEATURE_LIGHT_GROUPS,
    CONF_OVERHEAD_LIGHTS,
    CONF_OVERHEAD_LIGHTS_ACT_ON,
    CONF_OVERHEAD_LIGHTS_BLOCKING_STATES,
    CONF_ACCENT_LIGHTS_BRIGHTNESS,
    CONF_OVERHEAD_LIGHTS_BRIGHTNESS,
    CONF_OVERHEAD_LIGHTS_REQUIRE_DARK,
    CONF_OVERHEAD_LIGHTS_STATES,
    CONF_OVERHEAD_LIGHTS_TURN_OFF_WHEN_BRIGHT,
    CONF_SECONDARY_STATES,
    CONF_SLEEP_ENTITY,
    DATA_AREA_OBJECT,
    DOMAIN,
    LIGHT_GROUP_ACT_ON_OPTIONS,
    LIGHT_GROUP_ACT_ON_OCCUPANCY_CHANGE,
    LIGHT_GROUP_BRIGHTNESS_DARK_ON_BRIGHT_OFF,
    LIGHT_GROUP_BRIGHTNESS_IGNORE,
    MODULE_DATA,
    AreaStates,
)
from custom_components.adaptive_areas.light import AreaLightGroup

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
        },
        CONF_ENABLED_FEATURES: {
            CONF_FEATURE_LIGHT: {"turn_on_below": 90.0, "turn_off_above": 110.0},
            CONF_FEATURE_LIGHT_GROUPS: {
                CONF_OVERHEAD_LIGHTS: ["light.mock_light_1"],
                CONF_OVERHEAD_LIGHTS_ACT_ON: LIGHT_GROUP_ACT_ON_OPTIONS,
                CONF_OVERHEAD_LIGHTS_STATES: [AreaStates.OCCUPIED],
                CONF_OVERHEAD_LIGHTS_BLOCKING_STATES: [AreaStates.SLEEP],
                CONF_OVERHEAD_LIGHTS_TURN_OFF_WHEN_BRIGHT: True,
            },
        },
        CONF_GLOBAL_OPTIONS: {CONF_GLOBAL_LIGHT_SENSOR: GLOBAL_LUX_SENSOR},
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
        CONF_ENABLED_FEATURES: {
            CONF_FEATURE_LIGHT: {"turn_on_below": 90.0, "turn_off_above": 110.0},
            CONF_FEATURE_LIGHT_GROUPS: {
                CONF_OVERHEAD_LIGHTS: ["light.mock_light_1"],
                CONF_OVERHEAD_LIGHTS_ACT_ON: LIGHT_GROUP_ACT_ON_OPTIONS,
                CONF_OVERHEAD_LIGHTS_STATES: [AreaStates.OCCUPIED],
            },
        },
        CONF_GLOBAL_OPTIONS: {CONF_GLOBAL_LIGHT_SENSOR: GLOBAL_LUX_SENSOR},
    }
    return MockConfigEntry(
        domain=DOMAIN,
        data=data,
        options=options,
    )


GLOBAL_LUX_SENSOR = "sensor.test_global_lux"
DARK_LUX = "50"  # at or below the turn-on limit (90 lx)
BRIGHT_LUX = "150"  # above the turn-off limit (110 lx)


async def _set_brightness(hass: HomeAssistant, lux: str) -> None:
    """Set the area brightness through the global light sensor (the only DARK/BRIGHT source)."""
    hass.states.async_set(GLOBAL_LUX_SENSOR, lux, {"unit_of_measurement": "lx"})
    await hass.async_block_till_done()


@pytest.fixture(name="light_groups_lux_config_entry")
def mock_config_entry_light_groups_lux() -> MockConfigEntry:
    """Light group with a valid Lux configuration and a controlled global sensor.

    The overhead group keeps the default require_dark mode, so the brightness
    classification must return DARK for the turn-on to happen. The Lux limits are
    90 lx and 110 lx (threshold 100 lx, hysteresis 20 %).
    """
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    data.update(
        {
            CONF_ENABLED_FEATURES: {
                CONF_FEATURE_LIGHT: {"turn_on_below": 90.0, "turn_off_above": 110.0},
                CONF_FEATURE_LIGHT_GROUPS: {
                    CONF_OVERHEAD_LIGHTS: ["light.mock_light_1"],
                    CONF_OVERHEAD_LIGHTS_ACT_ON: [LIGHT_GROUP_ACT_ON_OCCUPANCY_CHANGE],
                    CONF_OVERHEAD_LIGHTS_STATES: [AreaStates.OCCUPIED],
                },
            }
        }
    )
    return MockConfigEntry(
        domain=DOMAIN,
        data=data,
        options={CONF_GLOBAL_OPTIONS: {CONF_GLOBAL_LIGHT_SENSOR: GLOBAL_LUX_SENSOR}},
    )


@pytest.fixture(name="_setup_integration_light_groups_lux")
async def setup_integration_light_groups_lux(
    hass: HomeAssistant,
    light_groups_lux_config_entry: MockConfigEntry,
) -> AsyncGenerator[Any]:
    """Set up the Lux-configured light group test with an isolated light policy.

    Isolation boundary: `LightRuntimeManager.async_setup`. That method installs the
    policy's state listeners and its first evaluation. It is replaced only while this
    fixture is active, so the policy never dispatches. The brightness classification
    (helpers/brightness.py) is not patched; it reads the global sensor directly.
    """
    # DARK reading: 50 lx is at or below the 90 lx turn-on limit.
    hass.states.async_set(GLOBAL_LUX_SENSOR, "50", {"unit_of_measurement": "lx"})

    async def _inert_policy_setup(self) -> None:
        """Keep the manager object, install no listeners, dispatch nothing."""

    with patch(
        "custom_components.adaptive_areas.helpers.light_runtime.LightRuntimeManager.async_setup",
        _inert_policy_setup,
    ):
        await init_integration(hass, [light_groups_lux_config_entry])
        yield
    await shutdown_integration(hass, [light_groups_lux_config_entry])


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


def test_existing_light_group_manual_override_behavior() -> None:
    """Manual ON and complete manual OFF during occupation set the override.

    Product rule: a complete manual switch-off during occupation keeps the override. It ends
    only with CLEAR or an effective blocker, never with the switch-off itself.
    """
    from unittest.mock import Mock

    group = object.__new__(AreaLightGroup)
    group.controlling = False
    group.manual_override = False
    group.area = Mock()
    group.area.is_occupied.return_value = True
    group._attr_extra_state_attributes = {}
    group._attr_name = "Test light group"
    group._attr_translation_key = None
    group.logger = _LOGGER

    assert group.handle_manual_group_state_change(STATE_ON)
    assert group.manual_override
    assert group.controlling

    assert group.handle_manual_group_state_change(STATE_OFF)
    assert group.manual_override
    assert group.controlling


async def test_light_group_basic(
    hass: HomeAssistant,
    light_groups_lux_config_entry: MockConfigEntry,
    entities_light_one: list[MockLight],
    entities_binary_sensor_motion_one: list[MockBinarySensor],
    _setup_integration_light_groups_lux,
) -> None:
    """Test light group."""

    mock_light_entity_id = entities_light_one[0].entity_id
    mock_motion_sensor_entity_id = entities_binary_sensor_motion_one[0].entity_id
    light_group_entity_id = f"{LIGHT_DOMAIN}.adaptive_areas_light_groups_{DEFAULT_MOCK_AREA}_overhead_lights"
    light_control_entity_id = (
        f"{SWITCH_DOMAIN}.adaptive_areas_light_groups_{DEFAULT_MOCK_AREA}_light_control"
    )
    area_sensor_entity_id = f"{BINARY_SENSOR_DOMAIN}.adaptive_areas_presence_tracking_{DEFAULT_MOCK_AREA}_area_state"

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

    # Check light group is on
    light_group_state = hass.states.get(light_group_entity_id)
    assert_state(light_group_state, STATE_ON)
    area = hass.data[MODULE_DATA][light_groups_lux_config_entry.entry_id][
        DATA_AREA_OBJECT
    ]
    assert any(
        entry["feature"] == "light_groups"
        and entry["decision"] == "turn_on"
        and entry["outcome"] == "executed"
        for entry in area.decision_trace.export()
    )

    # Isolation proof: the real brightness classification saw DARK, and the isolated
    # light policy never dispatched anything.
    from custom_components.adaptive_areas.helpers.brightness import (
        BrightnessState,
        area_brightness,
    )

    assert area_brightness(hass, area).state is BrightnessState.DARK
    assert area.light_runtime_manager.last_dispatched_action is None

    # Turn motion sensor off
    hass.states.async_set(mock_motion_sensor_entity_id, STATE_OFF)
    await hass.async_block_till_done()

    # Test area state is STATE_OFF
    area_state = hass.states.get(area_sensor_entity_id)
    assert_state(area_state, STATE_OFF)

    # Check light group is off
    light_group_state = hass.states.get(light_group_entity_id)
    assert_state(light_group_state, STATE_OFF)
    assert any(
        entry["feature"] == "light_groups"
        and entry["decision"] == "turn_off"
        and entry["outcome"] == "executed"
        for entry in area.decision_trace.export()
    )


async def test_light_group_blocking_state_turns_off(
    hass: HomeAssistant,
    entities_light_two: list[MockLight],
    entities_binary_sensor_motion_one: list[MockBinarySensor],
    entities_light_secondary_states: list[MockBinarySensor],
    _setup_integration_light_groups_advanced,
) -> None:
    """Test that a configured blocking state turns a group off."""
    light_group_entity_id = f"{LIGHT_DOMAIN}.adaptive_areas_light_groups_{DEFAULT_MOCK_AREA}_overhead_lights"
    light_control_entity_id = (
        f"{SWITCH_DOMAIN}.adaptive_areas_light_groups_{DEFAULT_MOCK_AREA}_light_control"
    )

    motion_sensor_entity_id = entities_binary_sensor_motion_one[0].entity_id
    sleep_sensor_entity_id = entities_light_secondary_states[0].entity_id

    hass.states.async_set(light_control_entity_id, STATE_ON)
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: light_control_entity_id}
    )
    await hass.async_block_till_done()

    # Keep area dark so lights can turn on.
    await _set_brightness(hass, DARK_LUX)
    hass.states.async_set(motion_sensor_entity_id, STATE_ON)
    await hass.async_block_till_done()

    light_group_state = hass.states.get(light_group_entity_id)
    assert_state(light_group_state, STATE_ON)

    unconfigured_light_id = entities_light_two[1].entity_id
    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: unconfigured_light_id},
        blocking=True,
    )

    hass.states.async_set(sleep_sensor_entity_id, STATE_ON)
    await hass.async_block_till_done()

    light_group_state = hass.states.get(light_group_entity_id)
    assert_state(light_group_state, STATE_OFF)
    assert hass.states.is_state(unconfigured_light_id, STATE_ON)

    # Losing a blocking state must also re-evaluate the group.
    hass.states.async_set(sleep_sensor_entity_id, STATE_OFF)
    await hass.async_block_till_done()

    light_group_state = hass.states.get(light_group_entity_id)
    assert_state(light_group_state, STATE_ON)


async def test_sleep_activation_does_not_turn_on_in_clear_area(
    hass: HomeAssistant,
    entities_light_one: list[MockLight],
    entities_binary_sensor_motion_one: list[MockBinarySensor],
    entities_light_secondary_states: list[MockBinarySensor],
    light_groups_advanced_config_entry: MockConfigEntry,
) -> None:
    """Sleep activation still requires the area to be occupied."""
    light_groups_advanced_config_entry.options[CONF_ENABLED_FEATURES][
        CONF_FEATURE_LIGHT_GROUPS
    ][CONF_OVERHEAD_LIGHTS_STATES] = [AreaStates.SLEEP]
    await init_integration(hass, [light_groups_advanced_config_entry])

    light_group_entity_id = f"{LIGHT_DOMAIN}.adaptive_areas_light_groups_{DEFAULT_MOCK_AREA}_overhead_lights"
    light_control_entity_id = (
        f"{SWITCH_DOMAIN}.adaptive_areas_light_groups_{DEFAULT_MOCK_AREA}_light_control"
    )
    sleep_sensor_entity_id = entities_light_secondary_states[0].entity_id

    hass.states.async_set(light_control_entity_id, STATE_ON)
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: light_control_entity_id}
    )
    hass.states.async_set(sleep_sensor_entity_id, STATE_ON)
    await hass.async_block_till_done()

    assert_state(hass.states.get(light_group_entity_id), STATE_OFF)
    await shutdown_integration(hass, [light_groups_advanced_config_entry])


async def test_light_group_turns_off_when_bright(
    hass: HomeAssistant,
    entities_light_two: list[MockLight],
    entities_binary_sensor_motion_one: list[MockBinarySensor],
    entities_light_secondary_states: list[MockBinarySensor],
    _setup_integration_light_groups_advanced,
) -> None:
    """Test that turn_off_when_bright actively turns the group's lights off.

    The second lamp is in no group. Once the global light sensor is configured, the Area
    policy controls such policy-only lamps as well, so it follows the policy (off when bright).
    """
    light_group_entity_id = f"{LIGHT_DOMAIN}.adaptive_areas_light_groups_{DEFAULT_MOCK_AREA}_overhead_lights"
    light_control_entity_id = (
        f"{SWITCH_DOMAIN}.adaptive_areas_light_groups_{DEFAULT_MOCK_AREA}_light_control"
    )

    motion_sensor_entity_id = entities_binary_sensor_motion_one[0].entity_id
    sleep_sensor_entity_id = entities_light_secondary_states[0].entity_id

    hass.states.async_set(light_control_entity_id, STATE_ON)
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: light_control_entity_id}
    )
    await hass.async_block_till_done()

    # Keep area dark so lights can turn on.
    await _set_brightness(hass, DARK_LUX)
    hass.states.async_set(sleep_sensor_entity_id, STATE_OFF)
    hass.states.async_set(motion_sensor_entity_id, STATE_ON)
    await hass.async_block_till_done()

    light_group_state = hass.states.get(light_group_entity_id)
    assert_state(light_group_state, STATE_ON)

    unconfigured_light_id = entities_light_two[1].entity_id
    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: unconfigured_light_id},
        blocking=True,
    )

    # Bright transition should actively turn off the group.
    await _set_brightness(hass, BRIGHT_LUX)
    await hass.async_block_till_done()

    light_group_state = hass.states.get(light_group_entity_id)
    assert_state(light_group_state, STATE_OFF)
    assert hass.states.is_state(unconfigured_light_id, STATE_OFF)


async def test_light_group_turns_back_on_when_dark_again(
    hass: HomeAssistant,
    entities_light_one: list[MockLight],
    entities_binary_sensor_motion_one: list[MockBinarySensor],
    entities_light_secondary_states: list[MockBinarySensor],
    _setup_integration_light_groups_advanced,
) -> None:
    """Test lights recover when transitioning from bright back to dark."""
    light_group_entity_id = f"{LIGHT_DOMAIN}.adaptive_areas_light_groups_{DEFAULT_MOCK_AREA}_overhead_lights"
    light_control_entity_id = (
        f"{SWITCH_DOMAIN}.adaptive_areas_light_groups_{DEFAULT_MOCK_AREA}_light_control"
    )

    motion_sensor_entity_id = entities_binary_sensor_motion_one[0].entity_id

    hass.states.async_set(light_control_entity_id, STATE_ON)
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: light_control_entity_id}
    )
    await hass.async_block_till_done()

    # Occupied + dark -> lights on.
    await _set_brightness(hass, DARK_LUX)
    hass.states.async_set(motion_sensor_entity_id, STATE_ON)
    await hass.async_block_till_done()

    light_group_state = hass.states.get(light_group_entity_id)
    assert_state(light_group_state, STATE_ON)

    # Bright -> lights off (configured behavior).
    await _set_brightness(hass, BRIGHT_LUX)
    await hass.async_block_till_done()

    light_group_state = hass.states.get(light_group_entity_id)
    assert_state(light_group_state, STATE_OFF)

    # Dark again while still occupied -> lights should turn back on and stay on.
    await _set_brightness(hass, DARK_LUX)
    await hass.async_block_till_done()

    light_group_state = hass.states.get(light_group_entity_id)
    assert_state(light_group_state, STATE_ON)


async def test_light_group_combined_brightness_behavior(
    hass: HomeAssistant,
    entities_light_one: list[MockLight],
    entities_binary_sensor_motion_one: list[MockBinarySensor],
    entities_light_secondary_states: list[MockBinarySensor],
    light_groups_bright_config_entry: MockConfigEntry,
) -> None:
    """Combined mode requires darkness and turns an active group off when bright."""
    light_groups_bright_config_entry.options[CONF_ENABLED_FEATURES][
        CONF_FEATURE_LIGHT_GROUPS
    ][CONF_OVERHEAD_LIGHTS_BRIGHTNESS] = LIGHT_GROUP_BRIGHTNESS_DARK_ON_BRIGHT_OFF
    await init_integration(hass, [light_groups_bright_config_entry])

    light_group_entity_id = f"{LIGHT_DOMAIN}.adaptive_areas_light_groups_{DEFAULT_MOCK_AREA}_overhead_lights"
    light_control_entity_id = (
        f"{SWITCH_DOMAIN}.adaptive_areas_light_groups_{DEFAULT_MOCK_AREA}_light_control"
    )
    motion_sensor_entity_id = entities_binary_sensor_motion_one[0].entity_id

    hass.states.async_set(light_control_entity_id, STATE_ON)
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: light_control_entity_id}
    )

    # Occupancy while bright must not switch the group on.
    await _set_brightness(hass, BRIGHT_LUX)
    hass.states.async_set(motion_sensor_entity_id, STATE_ON)
    await hass.async_block_till_done()
    assert_state(hass.states.get(light_group_entity_id), STATE_OFF)

    # Becoming dark switches the group on while the area remains occupied.
    await _set_brightness(hass, DARK_LUX)
    await hass.async_block_till_done()
    assert_state(hass.states.get(light_group_entity_id), STATE_ON)

    # Becoming bright again actively switches the group off.
    await _set_brightness(hass, BRIGHT_LUX)
    await hass.async_block_till_done()
    assert_state(hass.states.get(light_group_entity_id), STATE_OFF)

    await shutdown_integration(hass, [light_groups_bright_config_entry])


async def test_light_group_stays_on_when_bright_if_not_configured(
    hass: HomeAssistant,
    entities_light_one: list[MockLight],
    entities_binary_sensor_motion_one: list[MockBinarySensor],
    entities_light_secondary_states: list[MockBinarySensor],
    _setup_integration_light_groups_bright,
) -> None:
    """Test bright transitions do not turn off lights unless configured."""
    light_group_entity_id = f"{LIGHT_DOMAIN}.adaptive_areas_light_groups_{DEFAULT_MOCK_AREA}_overhead_lights"
    light_control_entity_id = (
        f"{SWITCH_DOMAIN}.adaptive_areas_light_groups_{DEFAULT_MOCK_AREA}_light_control"
    )

    motion_sensor_entity_id = entities_binary_sensor_motion_one[0].entity_id

    hass.states.async_set(light_control_entity_id, STATE_ON)
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: light_control_entity_id}
    )
    await hass.async_block_till_done()

    # Ensure occupied and dark first.
    await _set_brightness(hass, DARK_LUX)
    hass.states.async_set(motion_sensor_entity_id, STATE_ON)
    await hass.async_block_till_done()

    light_group_state = hass.states.get(light_group_entity_id)
    assert_state(light_group_state, STATE_ON)

    # Bright transition should not turn off without turn_off_when_bright enabled.
    await _set_brightness(hass, BRIGHT_LUX)
    await hass.async_block_till_done()

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
    light_group_entity_id = f"{LIGHT_DOMAIN}.adaptive_areas_light_groups_{DEFAULT_MOCK_AREA}_overhead_lights"
    light_control_entity_id = (
        f"{SWITCH_DOMAIN}.adaptive_areas_light_groups_{DEFAULT_MOCK_AREA}_light_control"
    )

    motion_sensor_entity_id = entities_binary_sensor_motion_one[0].entity_id

    hass.states.async_set(light_control_entity_id, STATE_ON)
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: light_control_entity_id}
    )
    await hass.async_block_till_done()

    # Reproduce startup ordering: brightness is known before occupancy is restored.
    await _set_brightness(hass, BRIGHT_LUX)
    await hass.async_block_till_done()
    hass.states.async_set(motion_sensor_entity_id, STATE_ON)
    await hass.async_block_till_done()

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

    light_group_entity_id = f"{LIGHT_DOMAIN}.adaptive_areas_light_groups_{DEFAULT_MOCK_AREA}_overhead_lights"
    light_control_entity_id = (
        f"{SWITCH_DOMAIN}.adaptive_areas_light_groups_{DEFAULT_MOCK_AREA}_light_control"
    )
    motion_sensor_entity_id = entities_binary_sensor_motion_one[0].entity_id

    hass.states.async_set(light_control_entity_id, STATE_ON)
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: light_control_entity_id}
    )
    await _set_brightness(hass, BRIGHT_LUX)
    await hass.async_block_till_done()
    hass.states.async_set(motion_sensor_entity_id, STATE_ON)
    await hass.async_block_till_done()

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
        f"{LIGHT_DOMAIN}.adaptive_areas_light_groups_{DEFAULT_MOCK_AREA}_all_lights"
    )
    overhead_group_entity_id = f"{LIGHT_DOMAIN}.adaptive_areas_light_groups_{DEFAULT_MOCK_AREA}_overhead_lights"
    accent_group_entity_id = (
        f"{LIGHT_DOMAIN}.adaptive_areas_light_groups_{DEFAULT_MOCK_AREA}_accent_lights"
    )

    all_lights_group_state = hass.states.get(all_lights_group_entity_id)
    assert all_lights_group_state is not None

    child_ids = all_lights_group_state.attributes["child_ids"]
    assert overhead_group_entity_id in child_ids
    assert accent_group_entity_id in child_ids


async def test_light_groups_only_control_configured_area_lights(
    hass: HomeAssistant,
    entities_binary_sensor_motion_one: list[MockBinarySensor],
) -> None:
    """Automatic control never targets unconfigured or removed Area lights."""
    lights = [
        MockLight(name=name, state="off", unique_id=name)
        for name in ("ceiling", "floor", "vitrine", "tv_backlight")
    ]
    await setup_mock_entities(hass, LIGHT_DOMAIN, {DEFAULT_MOCK_AREA: lights})
    ceiling, floor, vitrine, tv_backlight = [light.entity_id for light in lights]
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    data[CONF_ENABLED_FEATURES] = {
        CONF_FEATURE_LIGHT_GROUPS: {
            CONF_OVERHEAD_LIGHTS: [ceiling, "light.removed"],
            CONF_OVERHEAD_LIGHTS_ACT_ON: [LIGHT_GROUP_ACT_ON_OCCUPANCY_CHANGE],
            CONF_OVERHEAD_LIGHTS_STATES: [AreaStates.OCCUPIED],
            # The property is about membership, not brightness: no darkness is required.
            CONF_OVERHEAD_LIGHTS_BRIGHTNESS: LIGHT_GROUP_BRIGHTNESS_IGNORE,
            # Each lamp belongs to one individual group (ceiling is overhead only).
            CONF_ACCENT_LIGHTS: [floor],
            CONF_ACCENT_LIGHTS_ACT_ON: [LIGHT_GROUP_ACT_ON_OCCUPANCY_CHANGE],
            CONF_ACCENT_LIGHTS_STATES: [AreaStates.OCCUPIED],
            CONF_ACCENT_LIGHTS_BRIGHTNESS: LIGHT_GROUP_BRIGHTNESS_IGNORE,
        }
    }
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    await init_integration(hass, [entry])
    all_group_id = f"light.adaptive_areas_light_groups_{DEFAULT_MOCK_AREA}_all_lights"
    overhead_group_id = (
        f"light.adaptive_areas_light_groups_{DEFAULT_MOCK_AREA}_overhead_lights"
    )
    accent_group_id = (
        f"light.adaptive_areas_light_groups_{DEFAULT_MOCK_AREA}_accent_lights"
    )
    control_id = f"switch.adaptive_areas_light_groups_{DEFAULT_MOCK_AREA}_light_control"
    all_group = hass.states.get(all_group_id)
    overhead_group = hass.states.get(overhead_group_id)
    accent_group = hass.states.get(accent_group_id)
    assert all_group is not None
    assert overhead_group is not None
    assert accent_group is not None
    assert all_group.attributes["lights"] == [ceiling, floor]
    assert all_group.attributes[ATTR_ENTITY_ID] == [ceiling, floor]
    assert overhead_group.attributes["lights"] == [ceiling]
    assert accent_group.attributes["lights"] == [floor]
    assert "light.removed" not in overhead_group.attributes["lights"]

    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: control_id}, blocking=True
    )
    motion_id = entities_binary_sensor_motion_one[0].entity_id
    hass.states.async_set(motion_id, STATE_ON)
    await hass.async_block_till_done()
    assert hass.states.is_state(ceiling, STATE_ON)
    assert hass.states.is_state(floor, STATE_ON)
    assert hass.states.is_state(vitrine, STATE_OFF)
    assert hass.states.is_state(tv_backlight, STATE_OFF)

    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: [vitrine, tv_backlight]},
        blocking=True,
    )
    hass.states.async_set(motion_id, STATE_OFF)
    await hass.async_block_till_done()
    assert hass.states.is_state(ceiling, STATE_OFF)
    assert hass.states.is_state(floor, STATE_OFF)
    assert hass.states.is_state(vitrine, STATE_ON)
    assert hass.states.is_state(tv_backlight, STATE_ON)

    await shutdown_integration(hass, [entry])


async def test_light_groups_with_no_configured_lights_control_nothing(
    hass: HomeAssistant,
    entities_binary_sensor_motion_one: list[MockBinarySensor],
) -> None:
    """An enabled but empty feature creates no controlling light groups."""
    lights = [
        MockLight(name=f"unconfigured_{index}", state="on", unique_id=str(index))
        for index in range(2)
    ]
    await setup_mock_entities(hass, LIGHT_DOMAIN, {DEFAULT_MOCK_AREA: lights})
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    data[CONF_ENABLED_FEATURES] = {CONF_FEATURE_LIGHT_GROUPS: {}}
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    await init_integration(hass, [entry])
    all_group_id = f"light.adaptive_areas_light_groups_{DEFAULT_MOCK_AREA}_all_lights"
    assert hass.states.get(all_group_id) is None

    motion_id = entities_binary_sensor_motion_one[0].entity_id
    hass.states.async_set(motion_id, STATE_ON)
    await hass.async_block_till_done()
    hass.states.async_set(motion_id, STATE_OFF)
    await hass.async_block_till_done()
    assert all(hass.states.is_state(light.entity_id, STATE_ON) for light in lights)

    await shutdown_integration(hass, [entry])


@pytest.mark.parametrize("members_left_on", [0, 1])
@pytest.mark.parametrize("presence_control", [False, True])
async def test_presence_activity_restores_partial_group(
    hass: HomeAssistant,
    entities_binary_sensor_motion_one: list[MockBinarySensor],
    freezer,
    members_left_on: int,
    presence_control: bool,
) -> None:
    """Real sensor reports restore all members without fake transitions or double calls."""
    from homeassistant.helpers.entity_component import DATA_INSTANCES

    from custom_components.adaptive_areas.const import (
        CONF_CLEAR_TIMEOUT,
        CONF_PRESENCE_CONTROL_ENTITIES,
        EVENT_ADAPTIVE_AREAS_AREA,
        LIGHT_GROUP_ACTIVATION,
        LIGHT_GROUP_BRIGHTNESS,
        LightGroupCategory,
    )

    lights = [
        MockLight(name=f"activity_{index}", state="off", unique_id=f"activity_{index}")
        for index in range(3)
    ]
    decorative = MockLight(
        name="unconfigured_decorative",
        state="off",
        unique_id="unconfigured_decorative",
    )
    await setup_mock_entities(
        hass, LIGHT_DOMAIN, {DEFAULT_MOCK_AREA: [*lights, decorative]}
    )
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    gate_id = "person.light_presence_control"
    if presence_control:
        hass.states.async_set(gate_id, "home")
        data[CONF_PRESENCE_CONTROL_ENTITIES] = [gate_id]
        data[CONF_CLEAR_TIMEOUT] = 1
    data[CONF_ENABLED_FEATURES] = {
        CONF_FEATURE_LIGHT_GROUPS: {
            CONF_OVERHEAD_LIGHTS: [light.entity_id for light in lights],
            LIGHT_GROUP_ACTIVATION[LightGroupCategory.OVERHEAD]: "occupied",
            LIGHT_GROUP_BRIGHTNESS[LightGroupCategory.OVERHEAD]: "ignore",
        }
    }
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    await init_integration(hass, [entry])
    group_id = f"light.adaptive_areas_light_groups_{DEFAULT_MOCK_AREA}_overhead_lights"
    control_id = f"switch.adaptive_areas_light_groups_{DEFAULT_MOCK_AREA}_light_control"
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: control_id}, blocking=True
    )
    group = hass.data[DATA_INSTANCES][LIGHT_DOMAIN].get_entity(group_id)
    calls = []
    events = []
    from homeassistant.const import EVENT_CALL_SERVICE

    unsub_calls = hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)
    unsub_events = hass.bus.async_listen(EVENT_ADAPTIVE_AREAS_AREA, events.append)
    source = entities_binary_sensor_motion_one[0].entity_id
    hass.states.async_set(source, STATE_ON)
    await hass.async_block_till_done()

    def activation_calls():
        return [
            event
            for event in calls
            if event.data["domain"] == LIGHT_DOMAIN
            and event.data["service"] == SERVICE_TURN_ON
            and event.data["service_data"].get(ATTR_ENTITY_ID) == group_id
        ]

    assert len(activation_calls()) == 1
    assert all(hass.states.is_state(light.entity_id, STATE_ON) for light in lights)
    assert hass.states.is_state(decorative.entity_id, STATE_OFF)
    initial_events = list(events)
    # A partial group still reports on and must not suppress recovery.
    await hass.services.async_call(
        LIGHT_DOMAIN,
        "turn_off",
        {ATTR_ENTITY_ID: [light.entity_id for light in lights[members_left_on:]]},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert group.is_on == bool(members_left_on)
    if presence_control:
        hass.states.async_set(source, STATE_OFF)
        await hass.async_block_till_done()
        hass.states.async_set(gate_id, "not_home")
        await hass.async_block_till_done()
        freezer.tick(3)
        hass.states.async_set(source, STATE_ON)
        await hass.async_block_till_done()
        assert len(activation_calls()) == 1
        assert all(
            hass.states.is_state(light.entity_id, STATE_OFF)
            for light in lights[members_left_on:]
        )
        assert hass.states.is_state(decorative.entity_id, STATE_OFF)
        hass.states.async_set(gate_id, "home")
        await hass.async_block_till_done()
        assert len(activation_calls()) == 1
    freezer.tick(3)
    hass.states.async_set(source, STATE_ON)
    await hass.async_block_till_done()
    if members_left_on == 0:
        # Deliberate complete manual switch-off during occupation: the override holds and
        # presence activity must not switch the group on again (no time window).
        assert group.manual_override
        assert len(activation_calls()) == 1
        assert all(hass.states.is_state(light.entity_id, STATE_OFF) for light in lights)
    else:
        # Partly switched group without a complete manual switch-off: recovery is allowed.
        assert not group.manual_override
        assert len(activation_calls()) == 2
        assert all(hass.states.is_state(light.entity_id, STATE_ON) for light in lights)
    assert hass.states.is_state(decorative.entity_id, STATE_OFF)
    assert events == initial_events
    freezer.tick(3)
    hass.states.async_set(source, STATE_ON)
    await hass.async_block_till_done()
    assert len(activation_calls()) == (1 if members_left_on == 0 else 2)
    unsub_calls()
    unsub_events()
    await shutdown_integration(hass, [entry])
