"""Tests for switch groups."""

from collections.abc import AsyncGenerator
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.components.binary_sensor import DOMAIN as BINARY_SENSOR_DOMAIN
from homeassistant.components.switch.const import DOMAIN as SWITCH_DOMAIN
from homeassistant.const import ATTR_ENTITY_ID, SERVICE_TURN_ON, STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant

from custom_components.adaptive_areas.const import (
    CONF_ENABLED_FEATURES,
    CONF_FEATURE_SWITCH_GROUPS,
    CONF_SECONDARY_STATES,
    CONF_SLEEP_ENTITY,
    CONF_SLEEP_SWITCHES_ACTION,
    CONF_SLEEP_SWITCHES,
    CONF_SLEEP_SWITCHES_STATES,
    DOMAIN,
    SWITCH_GROUP_ACTION_TURN_OFF,
    AreaStates,
)
from tests.const import DEFAULT_MOCK_AREA
from tests.helpers import (
    assert_state,
    get_basic_config_entry_data,
    init_integration,
    setup_mock_entities,
    shutdown_integration,
)
from tests.mocks import MockBinarySensor, MockSwitch


@pytest.fixture(name="switch_groups_config_entry")
def mock_config_entry_switch_groups() -> MockConfigEntry:
    """Fixture for switch groups configuration."""
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    data.update(
        {
            CONF_SECONDARY_STATES: {
                CONF_SLEEP_ENTITY: "binary_sensor.sleep_sensor",
            },
            CONF_ENABLED_FEATURES: {
                CONF_FEATURE_SWITCH_GROUPS: {
                    CONF_SLEEP_SWITCHES: ["switch.mock_tv"],
                    CONF_SLEEP_SWITCHES_STATES: [AreaStates.SLEEP],
                    CONF_SLEEP_SWITCHES_ACTION: SWITCH_GROUP_ACTION_TURN_OFF,
                }
            },
        }
    )
    return MockConfigEntry(domain=DOMAIN, data=data)


@pytest.fixture(name="_setup_integration_switch_groups")
async def setup_integration_switch_groups(
    hass: HomeAssistant,
    switch_groups_config_entry: MockConfigEntry,
) -> AsyncGenerator[Any]:
    """Set up integration with switch groups."""
    await init_integration(hass, [switch_groups_config_entry])
    yield
    await shutdown_integration(hass, [switch_groups_config_entry])


@pytest.fixture(name="entities_switch_and_sleep")
async def setup_entities_switch_and_sleep(
    hass: HomeAssistant,
) -> list[Any]:
    """Create switch and sleep entities."""
    mock_switch_entities = [
        MockSwitch(name="mock_tv", state="off", unique_id="switch_1")
    ]
    mock_binary_sensor_entities = [
        MockBinarySensor(name="sleep_sensor", state="off", unique_id="sleep_1")
    ]
    await setup_mock_entities(
        hass, SWITCH_DOMAIN, {DEFAULT_MOCK_AREA: mock_switch_entities}
    )
    await setup_mock_entities(
        hass, BINARY_SENSOR_DOMAIN, {DEFAULT_MOCK_AREA: mock_binary_sensor_entities}
    )
    return [*mock_switch_entities, *mock_binary_sensor_entities]


async def test_switch_group_action_is_applied(
    hass: HomeAssistant,
    entities_switch_and_sleep: list[Any],
    entities_binary_sensor_motion_one: list[MockBinarySensor],
    _setup_integration_switch_groups,
) -> None:
    """Test switch group can execute configured off-action while state is active."""
    switch_group_entity_id = f"{SWITCH_DOMAIN}.adaptive_areas_switch_groups_{DEFAULT_MOCK_AREA}_sleep_switches"
    switch_control_entity_id = f"{SWITCH_DOMAIN}.adaptive_areas_switch_groups_{DEFAULT_MOCK_AREA}_switch_group_control"
    sleep_sensor_entity_id = "binary_sensor.sleep_sensor"
    motion_sensor_entity_id = entities_binary_sensor_motion_one[0].entity_id

    hass.states.async_set(switch_control_entity_id, STATE_ON)
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: switch_control_entity_id}
    )
    await hass.async_block_till_done()

    hass.states.async_set(motion_sensor_entity_id, STATE_ON)
    await hass.async_block_till_done()
    hass.states.async_set(sleep_sensor_entity_id, STATE_ON)
    await hass.async_block_till_done()
    await hass.async_block_till_done()

    switch_group_state = hass.states.get(switch_group_entity_id)
    assert_state(switch_group_state, STATE_OFF)

    hass.states.async_set(sleep_sensor_entity_id, STATE_OFF)
    await hass.async_block_till_done()
    await hass.async_block_till_done()

    switch_group_state = hass.states.get(switch_group_entity_id)
    assert_state(switch_group_state, STATE_ON)
