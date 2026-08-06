"""Tests for config flow behavior."""

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.const import ATTR_NAME

from custom_components.magic_areas.config_flow import OptionsFlowHandler
from custom_components.magic_areas.const import (
    AREA_STATE_BRIGHT,
    CONF_ENABLED_FEATURES,
    CONF_FEATURE_LIGHT_GROUPS,
    CONF_OVERHEAD_LIGHTS_BLOCKING_STATES,
    CONF_OVERHEAD_LIGHTS_TURN_OFF_WHEN_BRIGHT,
    DOMAIN,
)
from tests.const import DEFAULT_MOCK_AREA
from tests.helpers import (
    get_basic_config_entry_data,
    init_integration,
    shutdown_integration,
)


async def test_options_flow_keeps_extended_light_group_options(hass) -> None:
    """Test that extended light-group options survive reopening options flow."""

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
    assert (
        flow.area_options[CONF_ENABLED_FEATURES][CONF_FEATURE_LIGHT_GROUPS][
            CONF_OVERHEAD_LIGHTS_BLOCKING_STATES
        ]
        == [AREA_STATE_BRIGHT]
    )
    assert (
        flow.area_options[CONF_ENABLED_FEATURES][CONF_FEATURE_LIGHT_GROUPS][
            CONF_OVERHEAD_LIGHTS_TURN_OFF_WHEN_BRIGHT
        ]
        is True
    )

    await shutdown_integration(hass, [config_entry])
