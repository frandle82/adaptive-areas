"""Tests for config flow behavior."""

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.const import ATTR_NAME

from custom_components.magic_areas.config_flow import OptionsFlowHandler
from custom_components.magic_areas.const import (
    AREA_STATE_BRIGHT,
    AREA_STATE_EXTENDED,
    CONF_OVERHEAD_LIGHTS_ACTIVATION,
    CONF_ENABLED_FEATURES,
    CONF_FEATURE_LIGHT_GROUPS,
    CONF_OVERHEAD_LIGHTS_BLOCKING_STATES,
    CONF_OVERHEAD_LIGHTS_BRIGHTNESS,
    CONF_OVERHEAD_LIGHTS_TURN_OFF_WHEN_BRIGHT,
    DOMAIN,
    LIGHT_GROUP_ACTIVATION_EXTENDED,
    LIGHT_GROUP_BRIGHTNESS_TURN_OFF,
)
from tests.const import DEFAULT_MOCK_AREA
from tests.helpers import (
    get_basic_config_entry_data,
    init_integration,
    shutdown_integration,
)


async def test_options_flow_migrates_legacy_light_group_options(hass) -> None:
    """Test that legacy light-group options are migrated before reopening the flow."""

    config_entry_options = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    config_entry_options[CONF_ENABLED_FEATURES] = {
        CONF_FEATURE_LIGHT_GROUPS: {
            CONF_OVERHEAD_LIGHTS_BLOCKING_STATES: [AREA_STATE_BRIGHT],
            CONF_OVERHEAD_LIGHTS_TURN_OFF_WHEN_BRIGHT: True,
        }
    }

    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title=str(config_entry_options[ATTR_NAME]),
        data=get_basic_config_entry_data(DEFAULT_MOCK_AREA),
        options=config_entry_options,
    )
    await init_integration(hass, [config_entry])

    flow = OptionsFlowHandler()
    flow.hass = hass
    flow.handler = config_entry.entry_id

    result = await flow.async_step_init()

    assert result["type"] == "menu"
    light_config = flow.area_options[CONF_ENABLED_FEATURES][CONF_FEATURE_LIGHT_GROUPS]
    assert light_config[CONF_OVERHEAD_LIGHTS_BLOCKING_STATES] == []
    assert (
        light_config[CONF_OVERHEAD_LIGHTS_BRIGHTNESS] == LIGHT_GROUP_BRIGHTNESS_TURN_OFF
    )
    assert CONF_OVERHEAD_LIGHTS_TURN_OFF_WHEN_BRIGHT not in light_config

    await shutdown_integration(hass, [config_entry])


async def test_light_group_form_only_exposes_room_state_rules(hass) -> None:
    """Test that light groups use the simplified room-state configuration."""
    config_entry_options = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    config_entry_options[CONF_ENABLED_FEATURES] = {CONF_FEATURE_LIGHT_GROUPS: {}}
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title=str(config_entry_options[ATTR_NAME]),
        data=get_basic_config_entry_data(DEFAULT_MOCK_AREA),
        options=config_entry_options,
    )
    await init_integration(hass, [config_entry])

    flow = OptionsFlowHandler()
    flow.hass = hass
    flow.handler = config_entry.entry_id
    await flow.async_step_init()
    result = await flow.async_step_feature_conf_light_groups()

    assert result["type"] == "form"
    field_names = {marker.schema for marker in result["data_schema"].schema}
    assert "overhead_lights_activation" in field_names
    assert "overhead_lights_blocking_states" in field_names
    assert "overhead_lights_brightness" in field_names
    assert "overhead_lights_states" not in field_names
    assert "overhead_lights_require_dark" not in field_names
    assert "overhead_lights_turn_off_when_bright" not in field_names
    assert "overhead_lights_act_on" not in field_names
    assert "overhead_lights_state_rules_rule_1" not in field_names
    assert "overhead_lights_states_logic" not in field_names

    invalid_result = await flow.async_step_feature_conf_light_groups(
        {CONF_OVERHEAD_LIGHTS_BLOCKING_STATES: [AREA_STATE_BRIGHT]}
    )
    assert invalid_result["type"] == "form"
    assert invalid_result["errors"] == {
        CONF_OVERHEAD_LIGHTS_BLOCKING_STATES: "malformed_input"
    }

    conflicting_result = await flow.async_step_feature_conf_light_groups(
        {
            CONF_OVERHEAD_LIGHTS_ACTIVATION: LIGHT_GROUP_ACTIVATION_EXTENDED,
            CONF_OVERHEAD_LIGHTS_BLOCKING_STATES: [AREA_STATE_EXTENDED],
        }
    )
    assert conflicting_result["type"] == "form"
    assert conflicting_result["errors"] == {
        CONF_OVERHEAD_LIGHTS_BLOCKING_STATES: "malformed_input"
    }

    await shutdown_integration(hass, [config_entry])
