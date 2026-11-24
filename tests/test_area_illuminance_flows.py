"""D01: the Area brightness sensor in the Options Flow and in the repairs.

Same key, same validation as the dashboard (area_config.illuminance_sensor_error).
The legacy binary dark entity is ignored and never reported as a repair.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.adaptive_areas.const import (
    CONF_AREA_ILLUMINANCE_SENSOR,
    CONF_SECONDARY_STATES,
    DOMAIN,
)
from custom_components.adaptive_areas.repairs import async_evaluate_config_entry
from tests.helpers import get_basic_config_entry_data
from tests.const import MockAreaIds

LUX = "sensor.flow_lux"
BINARY = "binary_sensor.flow_dark"


async def _open_secondary_step(hass: HomeAssistant, entry) -> dict:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    return await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "secondary_states"}
    )


async def test_options_flow_offers_the_area_sensor_and_refuses_a_binary_entity(
    hass: HomeAssistant, basic_config_entry, _setup_integration_basic
) -> None:
    """The secondary states step shows the Area sensor; a binary entity is refused."""
    hass.states.async_set(BINARY, "on", {"device_class": "light"})
    form = await _open_secondary_step(hass, basic_config_entry)
    assert form["step_id"] == "secondary_states"
    assert CONF_AREA_ILLUMINANCE_SENSOR in {str(k) for k in form["data_schema"].schema}
    result = await hass.config_entries.options.async_configure(
        form["flow_id"], {CONF_AREA_ILLUMINANCE_SENSOR: BINARY}
    )
    assert result["errors"] == {
        CONF_AREA_ILLUMINANCE_SENSOR: "expected_illuminance_sensor"
    }
    assert CONF_AREA_ILLUMINANCE_SENSOR not in basic_config_entry.options


async def test_options_flow_stores_a_lux_sensor_at_area_level(
    hass: HomeAssistant, basic_config_entry, _setup_integration_basic
) -> None:
    """A valid lx sensor is saved at Area level when the options flow is finished."""
    hass.states.async_set(LUX, "40", {"unit_of_measurement": "lx"})
    form = await _open_secondary_step(hass, basic_config_entry)
    menu = await hass.config_entries.options.async_configure(
        form["flow_id"], {CONF_AREA_ILLUMINANCE_SENSOR: LUX}
    )
    assert menu.get("errors") in (None, {}), menu
    await hass.config_entries.options.async_configure(
        menu["flow_id"], {"next_step_id": "finish"}
    )
    await hass.async_block_till_done()
    assert basic_config_entry.options.get(CONF_AREA_ILLUMINANCE_SENSOR) == LUX
    assert CONF_AREA_ILLUMINANCE_SENSOR not in (
        basic_config_entry.options.get(CONF_SECONDARY_STATES) or {}
    )


async def test_repairs_report_a_missing_area_sensor_and_ignore_the_legacy_dark_entity(
    hass: HomeAssistant,
) -> None:
    """A deleted Area sensor is a missing reference; a legacy binary dark entity is not."""
    data = get_basic_config_entry_data(MockAreaIds.KITCHEN)
    data[CONF_AREA_ILLUMINANCE_SENSOR] = "sensor.deleted_area_lux"
    entry = MockConfigEntry(domain=DOMAIN, title="Safe entry", data=data)
    summary = await async_evaluate_config_entry(hass, entry)
    assert summary["missing_entities"]["category_counts"] == {"area_illuminance": 1}

    legacy = get_basic_config_entry_data(MockAreaIds.KITCHEN)
    legacy[CONF_SECONDARY_STATES] = {"dark_entity": "binary_sensor.deleted_dark"}
    entry = MockConfigEntry(domain=DOMAIN, title="Safe entry", data=legacy)
    summary = await async_evaluate_config_entry(hass, entry)
    assert summary["missing_entities"]["count"] == 0
