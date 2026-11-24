"""D01: the Area brightness sensor is the first source of the Light decision.

Priority: the Area's own `illuminance_entity`, then the global light sensor, then UNKNOWN.
A configured but unavailable Area sensor is UNKNOWN and never falls back to the global one.
A binary dark entity (secondary state `dark_entity`) is never read as a lux value.
"""

from __future__ import annotations

from itertools import count
from types import SimpleNamespace

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import ATTR_DEVICE_CLASS, STATE_OFF, STATE_ON
from homeassistant.helpers.area_registry import async_get as async_get_area_registry
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.adaptive_areas.base.adaptive import AdaptiveArea
from custom_components.adaptive_areas.const import (
    AREA_STATE_OCCUPIED,
    AREA_TYPE_INTERIOR,
    CONF_ENABLED_FEATURES,
    CONF_FEATURE_LIGHT,
    CONF_GLOBAL_ENTRY,
    CONF_GLOBAL_LIGHT_SENSOR,
    CONF_GLOBAL_OPTIONS,
    CONF_ID,
    CONF_INCLUDE_ENTITIES,
    CONF_NAME,
    CONF_PRESENCE_DEVICE_PLATFORMS,
    CONF_PRESENCE_SENSOR_DEVICE_CLASS,
    CONF_SECONDARY_STATES,
    CONF_TYPE,
    CONF_DARK_ENTITY,
    CONF_AREA_ILLUMINANCE_SENSOR,
    DOMAIN,
)
from custom_components.adaptive_areas.helpers.brightness import (
    BrightnessState,
    area_brightness,
)
from custom_components.adaptive_areas.helpers.light_policy import (
    LightPolicyAction,
    evaluate_light_policy,
)
from custom_components.adaptive_areas.helpers.sources import (
    light_illuminance_entity_id,
    light_source_snapshot,
)

GLOBAL_LUX = "sensor.global_lux"
AREA_LUX = "sensor.area_lux"
DARK_BINARY = "binary_sensor.hall_dark"
_NUMBER = count(1)


def _area(
    hass,
    *,
    feature: dict,
    secondary: dict | None = None,
    illuminance: str | None = None,
):
    name = f"Hall {next(_NUMBER)}"
    area_entry = async_get_area_registry(hass).async_create(name)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_GLOBAL_ENTRY: True},
        options={CONF_GLOBAL_OPTIONS: {CONF_GLOBAL_LIGHT_SENSOR: GLOBAL_LUX}},
    )
    entry.add_to_hass(hass)
    hass.states.async_set("light.hall", STATE_OFF)
    hass.states.async_set(
        "binary_sensor.hall_motion",
        STATE_ON,
        {ATTR_DEVICE_CLASS: BinarySensorDeviceClass.MOTION},
    )
    config = {
        CONF_ID: area_entry.id,
        CONF_NAME: name,
        CONF_TYPE: AREA_TYPE_INTERIOR,
        CONF_PRESENCE_DEVICE_PLATFORMS: ["binary_sensor"],
        CONF_PRESENCE_SENSOR_DEVICE_CLASS: [BinarySensorDeviceClass.MOTION],
        CONF_INCLUDE_ENTITIES: ["light.hall", "binary_sensor.hall_motion"],
        CONF_ENABLED_FEATURES: {CONF_FEATURE_LIGHT: feature},
    }
    if secondary is not None:
        config[CONF_SECONDARY_STATES] = secondary
    if illuminance is not None:
        config[CONF_AREA_ILLUMINANCE_SENSOR] = illuminance
    area = AdaptiveArea(
        hass,
        SimpleNamespace(id=area_entry.id, name=name, icon=None, floor_id=None),
        entry,
        config,
    )
    area.states = [AREA_STATE_OCCUPIED]
    return area


def _lux(hass, entity_id: str, value: str) -> None:
    hass.states.async_set(
        entity_id,
        value,
        {"unit_of_measurement": "lx", ATTR_DEVICE_CLASS: SensorDeviceClass.ILLUMINANCE},
    )


THRESHOLDS = {"turn_on_below": 100.0, "turn_off_above": 120.0}


async def test_area_sensor_is_used_before_global(hass) -> None:
    """A configured Area sensor is the source; the global sensor is not consulted."""
    _lux(hass, GLOBAL_LUX, "500")
    _lux(hass, AREA_LUX, "40")
    area = _area(hass, feature=dict(THRESHOLDS), illuminance=AREA_LUX)
    assert light_illuminance_entity_id(area) == AREA_LUX
    snapshot = light_source_snapshot(area)
    assert snapshot.illuminance_entity_id == AREA_LUX
    assert snapshot.illuminance_value == 40.0
    assert (
        evaluate_light_policy(snapshot, _policy(area)).action
        is LightPolicyAction.TURN_ON
    )


async def test_global_sensor_is_used_without_area_sensor(hass) -> None:
    """Without an Area sensor the global light sensor remains the source (no migration)."""
    _lux(hass, GLOBAL_LUX, "40")
    area = _area(hass, feature=dict(THRESHOLDS))
    assert light_illuminance_entity_id(area) == GLOBAL_LUX
    assert light_source_snapshot(area).illuminance_entity_id == GLOBAL_LUX


async def test_unavailable_area_sensor_is_unknown_and_never_falls_back(hass) -> None:
    """A configured, unavailable Area sensor stays the source: UNKNOWN, no global fallback."""
    _lux(hass, GLOBAL_LUX, "40")
    hass.states.async_set(AREA_LUX, "unavailable")
    area = _area(hass, feature=dict(THRESHOLDS), illuminance=AREA_LUX)
    snapshot = light_source_snapshot(area)
    assert snapshot.illuminance_entity_id == AREA_LUX
    assert snapshot.illuminance_available is False
    assert snapshot.illuminance_value is None
    assert (
        evaluate_light_policy(snapshot, _policy(area)).action
        is not LightPolicyAction.TURN_ON
    )
    result = area_brightness(hass, area)
    assert result.state is BrightnessState.UNKNOWN


async def test_binary_dark_entity_is_never_a_lux_value(hass) -> None:
    """The secondary dark entity is a binary state source, not the Area brightness sensor."""
    _lux(hass, GLOBAL_LUX, "300")
    hass.states.async_set(DARK_BINARY, STATE_ON, {ATTR_DEVICE_CLASS: "light"})
    area = _area(
        hass,
        feature=dict(THRESHOLDS),
        secondary={CONF_DARK_ENTITY: DARK_BINARY},
    )
    assert light_illuminance_entity_id(area) == GLOBAL_LUX
    assert light_source_snapshot(area).illuminance_value == 300.0


async def test_sensor_change_drops_hysteresis_and_uses_new_sensor(hass) -> None:
    """Changing the Area sensor invalidates the remembered brightness and reads the new one."""
    _lux(hass, AREA_LUX, "40")
    # Inside the hysteresis band: a remembered DARK would wrongly survive the change.
    _lux(hass, "sensor.area_lux_b", "110")
    area = _area(hass, feature=dict(THRESHOLDS), illuminance=AREA_LUX)
    assert area_brightness(hass, area).state is BrightnessState.DARK
    area.config[CONF_ENABLED_FEATURES][CONF_FEATURE_LIGHT][
        "illuminance_entity"
    ] = "sensor.area_lux_b"
    result = area_brightness(hass, area)
    assert result.state is BrightnessState.UNKNOWN


def _policy(area):
    from custom_components.adaptive_areas.helpers.light_policy import (
        light_policy_config_from_feature,
    )

    return light_policy_config_from_feature(area.feature_config(CONF_FEATURE_LIGHT))


# --- Backend validation on save and the single Area field (real config entry) ---

from unittest.mock import AsyncMock, patch  # noqa: E402

import pytest  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402

from custom_components.adaptive_areas.area_config import async_update_area  # noqa: E402


@pytest.mark.parametrize(
    ("entity_id", "attributes", "expected"),
    [
        (
            "binary_sensor.hall_dark",
            {"device_class": "light"},
            "Expected an illuminance sensor",
        ),
        (
            "sensor.temperature",
            {"unit_of_measurement": "°C"},
            "Expected an illuminance sensor",
        ),
        ("sensor.missing_lux", None, "Unknown illuminance sensor"),
    ],
)
async def test_save_refuses_non_illuminance_sources(
    hass: HomeAssistant,
    basic_config_entry,
    _setup_integration_basic,
    entity_id,
    attributes,
    expected,
) -> None:
    """Only a numeric illuminance sensor (lx) is saved as the Area brightness sensor."""
    if attributes is not None:
        hass.states.async_set(
            entity_id, "on" if entity_id.startswith("binary") else "20", attributes
        )
    with patch.object(hass.config_entries, "async_reload", new_callable=AsyncMock):
        errors = await async_update_area(
            hass, basic_config_entry, {CONF_AREA_ILLUMINANCE_SENSOR: entity_id}
        )
    assert errors == {CONF_AREA_ILLUMINANCE_SENSOR: expected}
    assert CONF_AREA_ILLUMINANCE_SENSOR not in basic_config_entry.options


async def test_save_accepts_lux_sensor_and_keeps_light_feature_unchanged(
    hass: HomeAssistant, basic_config_entry, _setup_integration_basic
) -> None:
    """A valid lx sensor is stored at Area level; the Light feature keeps its own keys only."""
    hass.states.async_set(AREA_LUX, "40", {"unit_of_measurement": "lx"})
    with patch.object(hass.config_entries, "async_reload", new_callable=AsyncMock):
        errors = await async_update_area(
            hass, basic_config_entry, {CONF_AREA_ILLUMINANCE_SENSOR: AREA_LUX}
        )
    assert errors == {}
    assert basic_config_entry.options.get(CONF_AREA_ILLUMINANCE_SENSOR) == AREA_LUX
    light = basic_config_entry.options.get(CONF_ENABLED_FEATURES, {}).get(
        CONF_FEATURE_LIGHT
    )
    assert light is None or set(light) <= {"turn_on_below", "turn_off_above"}


async def test_area_sensor_does_not_need_the_light_feature(
    hass: HomeAssistant, basic_config_entry, _setup_integration_basic
) -> None:
    """The brightness sensor is an Area property: it works without the Light feature."""
    hass.states.async_set(AREA_LUX, "40", {"unit_of_measurement": "lx"})
    with patch.object(hass.config_entries, "async_reload", new_callable=AsyncMock):
        await async_update_area(
            hass, basic_config_entry, {CONF_AREA_ILLUMINANCE_SENSOR: AREA_LUX}
        )
    assert CONF_FEATURE_LIGHT not in basic_config_entry.options.get(
        CONF_ENABLED_FEATURES, {}
    )
    area = _area(hass, feature={}, illuminance=AREA_LUX)
    assert light_illuminance_entity_id(area) == AREA_LUX


async def test_area_sensor_survives_reload_with_the_runtime_area(
    hass: HomeAssistant, basic_config_entry, _setup_integration_basic
) -> None:
    """After a real reload the runtime Area still reads the configured sensor."""
    from custom_components.adaptive_areas.helpers.area import iter_runtime_areas

    hass.states.async_set(AREA_LUX, "40", {"unit_of_measurement": "lx"})
    hass.states.async_set(GLOBAL_LUX, "500", {"unit_of_measurement": "lx"})
    await async_update_area(
        hass, basic_config_entry, {CONF_AREA_ILLUMINANCE_SENSOR: AREA_LUX}
    )
    await hass.async_block_till_done()
    await hass.config_entries.async_reload(basic_config_entry.entry_id)
    await hass.async_block_till_done()
    regular = [a for a in iter_runtime_areas(hass) if not a.is_meta()]
    assert len(regular) == 1
    assert light_illuminance_entity_id(regular[0]) == AREA_LUX


async def test_stored_sensor_that_is_temporarily_missing_does_not_block_other_saves(
    hass: HomeAssistant, basic_config_entry, _setup_integration_basic
) -> None:
    """A stored, currently unavailable Area sensor is kept; saving another setting succeeds."""
    hass.states.async_set(AREA_LUX, "40", {"unit_of_measurement": "lx"})
    with patch.object(hass.config_entries, "async_reload", new_callable=AsyncMock):
        await async_update_area(
            hass, basic_config_entry, {CONF_AREA_ILLUMINANCE_SENSOR: AREA_LUX}
        )
        hass.states.async_remove(AREA_LUX)
        errors = await async_update_area(hass, basic_config_entry, {"clear_timeout": 3})
    assert errors == {}
    assert basic_config_entry.options.get(CONF_AREA_ILLUMINANCE_SENSOR) == AREA_LUX
    assert basic_config_entry.options.get("clear_timeout") == 3
