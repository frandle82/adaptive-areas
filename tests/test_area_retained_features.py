"""D02: disabling a feature keeps its configuration (inactive); enabling restores it.

Real config entry, real update path (async_update_area) and a real reload. A parked feature
never runs: has_feature is false and the feature config is not read by the runtime.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant

from custom_components.adaptive_areas.area_config import async_update_area
from custom_components.adaptive_areas.const import (
    CONF_ENABLED_FEATURES,
    CONF_FEATURE_CLIMATE_CONTROL,
    CONF_FEATURE_LIGHT,
    CONF_RETAINED_FEATURES,
    CONF_CLIMATE_CONTROL_ENTITY_ID,
)

LIGHT_CONFIG = {"turn_on_below": 90.0, "turn_off_above": 110.0}


async def _update(hass, entry, updates):
    with patch.object(hass.config_entries, "async_reload", new_callable=AsyncMock):
        return await async_update_area(hass, entry, updates)


async def test_disabling_keeps_the_configuration_and_makes_it_inactive(
    hass: HomeAssistant, basic_config_entry, _setup_integration_basic
) -> None:
    """Disabling the Light feature parks its settings; the feature is not enabled."""
    assert (
        await _update(
            hass,
            basic_config_entry,
            {CONF_ENABLED_FEATURES: {CONF_FEATURE_LIGHT: dict(LIGHT_CONFIG)}},
        )
        == {}
    )
    assert await _update(hass, basic_config_entry, {CONF_ENABLED_FEATURES: {}}) == {}
    options = basic_config_entry.options
    assert CONF_FEATURE_LIGHT not in options[CONF_ENABLED_FEATURES]
    assert options[CONF_RETAINED_FEATURES][CONF_FEATURE_LIGHT] == LIGHT_CONFIG


async def test_reenabling_without_values_restores_the_parked_settings(
    hass: HomeAssistant, basic_config_entry, _setup_integration_basic
) -> None:
    """Enabling again with an empty configuration returns the previous settings."""
    await _update(
        hass,
        basic_config_entry,
        {CONF_ENABLED_FEATURES: {CONF_FEATURE_LIGHT: dict(LIGHT_CONFIG)}},
    )
    await _update(hass, basic_config_entry, {CONF_ENABLED_FEATURES: {}})
    assert (
        await _update(
            hass, basic_config_entry, {CONF_ENABLED_FEATURES: {CONF_FEATURE_LIGHT: {}}}
        )
        == {}
    )
    assert (
        basic_config_entry.options[CONF_ENABLED_FEATURES][CONF_FEATURE_LIGHT]
        == LIGHT_CONFIG
    )
    assert CONF_FEATURE_LIGHT not in basic_config_entry.options[CONF_RETAINED_FEATURES]


async def test_a_new_configuration_replaces_the_parked_one(
    hass: HomeAssistant, basic_config_entry, _setup_integration_basic
) -> None:
    """A submitted configuration on re-enabling wins; the parked copy is dropped."""
    await _update(
        hass,
        basic_config_entry,
        {CONF_ENABLED_FEATURES: {CONF_FEATURE_LIGHT: dict(LIGHT_CONFIG)}},
    )
    await _update(hass, basic_config_entry, {CONF_ENABLED_FEATURES: {}})
    new = {"turn_on_below": 40.0, "turn_off_above": 60.0}
    await _update(
        hass, basic_config_entry, {CONF_ENABLED_FEATURES: {CONF_FEATURE_LIGHT: new}}
    )
    assert basic_config_entry.options[CONF_ENABLED_FEATURES][CONF_FEATURE_LIGHT] == new
    assert CONF_FEATURE_LIGHT not in basic_config_entry.options[CONF_RETAINED_FEATURES]


async def test_other_saves_keep_the_parked_configuration(
    hass: HomeAssistant, basic_config_entry, _setup_integration_basic
) -> None:
    """Saving unrelated settings does not delete a parked feature configuration."""
    await _update(
        hass,
        basic_config_entry,
        {CONF_ENABLED_FEATURES: {CONF_FEATURE_LIGHT: dict(LIGHT_CONFIG)}},
    )
    await _update(hass, basic_config_entry, {CONF_ENABLED_FEATURES: {}})
    assert await _update(hass, basic_config_entry, {"clear_timeout": 4}) == {}
    assert (
        basic_config_entry.options[CONF_RETAINED_FEATURES][CONF_FEATURE_LIGHT]
        == LIGHT_CONFIG
    )
    assert basic_config_entry.options["clear_timeout"] == 4


async def test_parked_configuration_survives_a_reload(
    hass: HomeAssistant, basic_config_entry, _setup_integration_basic
) -> None:
    """After a real reload the parked configuration is still there and still inactive."""
    await _update(
        hass,
        basic_config_entry,
        {
            CONF_ENABLED_FEATURES: {
                CONF_FEATURE_CLIMATE_CONTROL: {
                    CONF_CLIMATE_CONTROL_ENTITY_ID: "climate.x"
                }
            }
        },
    )
    await _update(hass, basic_config_entry, {CONF_ENABLED_FEATURES: {}})
    await hass.config_entries.async_reload(basic_config_entry.entry_id)
    await hass.async_block_till_done()
    assert (
        CONF_FEATURE_CLIMATE_CONTROL
        in basic_config_entry.options[CONF_RETAINED_FEATURES]
    )
    assert (
        CONF_FEATURE_CLIMATE_CONTROL
        not in basic_config_entry.options[CONF_ENABLED_FEATURES]
    )


async def test_brightness_classification_works_without_the_light_feature(
    hass: HomeAssistant, basic_config_entry, _setup_integration_basic
) -> None:
    """2.4: with the Light feature disabled the parked limits still classify DARK and BRIGHT.

    A missing limit configuration stays UNKNOWN; UNKNOWN is never read as DARK or BRIGHT.
    """
    from custom_components.adaptive_areas.const import CONF_AREA_ILLUMINANCE_SENSOR
    from custom_components.adaptive_areas.helpers.area import iter_runtime_areas
    from custom_components.adaptive_areas.helpers.brightness import (
        BrightnessState,
        area_brightness,
    )

    lux = "sensor.no_light_lux"
    hass.states.async_set(lux, "40", {"unit_of_measurement": "lx"})
    await _update(hass, basic_config_entry, {CONF_AREA_ILLUMINANCE_SENSOR: lux})
    await _update(
        hass,
        basic_config_entry,
        {CONF_ENABLED_FEATURES: {CONF_FEATURE_LIGHT: dict(LIGHT_CONFIG)}},
    )
    await _update(hass, basic_config_entry, {CONF_ENABLED_FEATURES: {}})
    await hass.config_entries.async_reload(basic_config_entry.entry_id)
    await hass.async_block_till_done()
    (area,) = [a for a in iter_runtime_areas(hass) if not a.is_meta()]
    assert not area.has_feature(CONF_FEATURE_LIGHT)
    assert area_brightness(hass, area).state is BrightnessState.DARK

    hass.states.async_set(lux, "500", {"unit_of_measurement": "lx"})
    assert area_brightness(hass, area).state is BrightnessState.BRIGHT

    # No limits at all (none stored): UNKNOWN, never DARK. Checked on the runtime configuration.
    area.config[CONF_RETAINED_FEATURES] = {}
    hass.states.async_set(lux, "40", {"unit_of_measurement": "lx"})
    assert area_brightness(hass, area).state is BrightnessState.UNKNOWN
