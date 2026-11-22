"""Regression coverage for the global lux sensor feeding the Light policy."""

from itertools import count
from types import SimpleNamespace

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
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
    CONF_TYPE,
    DOMAIN,
)
from custom_components.adaptive_areas.helpers.light_policy import (
    LightPolicyAction,
    LightPolicyReason,
    evaluate_light_policy,
    light_policy_config_from_feature,
)
from custom_components.adaptive_areas.helpers.sources import light_source_snapshot
from custom_components.adaptive_areas.websocket import _validate_global_options

LUX_SENSOR = "sensor.hall_lux"
_AREA_NUMBER = count(1)
POLICY = light_policy_config_from_feature({"turn_on_below": 100, "turn_off_above": 120})


def _area(hass, lux_state: str | None, lux_class: str | None):
    name = f"Flur {next(_AREA_NUMBER)}"
    area_entry = async_get_area_registry(hass).async_create(name)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_GLOBAL_ENTRY: True},
        options={CONF_GLOBAL_OPTIONS: {CONF_GLOBAL_LIGHT_SENSOR: LUX_SENSOR}},
    )
    entry.add_to_hass(hass)
    if lux_state is not None:
        attributes = {"unit_of_measurement": "lx"}
        if lux_class is not None:
            attributes[ATTR_DEVICE_CLASS] = lux_class
        hass.states.async_set(LUX_SENSOR, lux_state, attributes)
    hass.states.async_set("light.hall", STATE_OFF)
    hass.states.async_set(
        "binary_sensor.hall_motion",
        STATE_ON,
        {ATTR_DEVICE_CLASS: BinarySensorDeviceClass.MOTION},
    )
    area = AdaptiveArea(
        hass,
        SimpleNamespace(id=area_entry.id, name=name, icon=None, floor_id=None),
        entry,
        {
            CONF_ID: area_entry.id,
            CONF_NAME: name,
            CONF_TYPE: AREA_TYPE_INTERIOR,
            CONF_PRESENCE_DEVICE_PLATFORMS: ["binary_sensor"],
            CONF_PRESENCE_SENSOR_DEVICE_CLASS: [BinarySensorDeviceClass.MOTION],
            CONF_INCLUDE_ENTITIES: ["light.hall", "binary_sensor.hall_motion"],
            CONF_ENABLED_FEATURES: {CONF_FEATURE_LIGHT: {}},
        },
    )
    area.states = [AREA_STATE_OCCUPIED]
    return area


def _decide(hass, lux_state: str | None):
    area = _area(hass, lux_state, SensorDeviceClass.ILLUMINANCE)
    snapshot = light_source_snapshot(area)
    return snapshot, evaluate_light_policy(snapshot, POLICY)


def test_zero_lux_is_a_valid_numeric_value_and_turns_dark_lights_on(hass) -> None:
    """0 lx must not be treated as missing data."""
    snapshot, decision = _decide(hass, "0")

    assert snapshot.illuminance_available is True
    assert snapshot.illuminance_value == 0.0
    assert decision.action is LightPolicyAction.TURN_ON
    assert decision.reason is LightPolicyReason.OCCUPIED_AND_DARK


def test_unavailable_unknown_and_non_numeric_lux_never_drive_decisions(hass) -> None:
    """Invalid states are reported as unavailable, never guessed."""
    for state in (STATE_UNAVAILABLE, STATE_UNKNOWN, "not-a-number", "nan"):
        snapshot, decision = _decide(hass, state)
        assert snapshot.illuminance_value is None, state
        assert decision.action is LightPolicyAction.NO_ACTION, state
        assert decision.reason is LightPolicyReason.ILLUMINANCE_UNAVAILABLE, state


def test_missing_lux_entity_is_unavailable(hass) -> None:
    """A configured but absent sensor is unavailable, not zero."""
    snapshot, decision = _decide(hass, None)

    assert snapshot.illuminance_entity_id == LUX_SENSOR
    assert snapshot.illuminance_available is False
    assert decision.reason is LightPolicyReason.ILLUMINANCE_UNAVAILABLE


def test_lux_boundaries_follow_documented_thresholds(hass) -> None:
    """At or below turn_on_below turns on; at or above turn_off_above turns off."""
    for value, expected in (
        ("100", LightPolicyAction.TURN_ON),
        ("101", LightPolicyAction.HOLD),
        ("119", LightPolicyAction.HOLD),
        ("120", LightPolicyAction.TURN_OFF),
    ):
        _, decision = _decide(hass, value)
        assert decision.action is expected, value


def test_global_lux_sensor_accepts_illuminance_class_or_lx_unit(hass) -> None:
    """Only illuminance class or the exact lx unit qualify; other units are rejected."""
    cases = {
        "illuminance_class": ({ATTR_DEVICE_CLASS: SensorDeviceClass.ILLUMINANCE}, None),
        "lx_unit": ({"unit_of_measurement": "lx"}, None),
        "percent": ({"unit_of_measurement": "%"}, "Expected an illuminance sensor"),
        "no_unit_no_class": ({}, "Expected an illuminance sensor"),
        "lux_spelled_out": (
            {"unit_of_measurement": "lux"},
            "Expected an illuminance sensor",
        ),
    }
    for name, (attributes, expected) in cases.items():
        hass.states.async_set(LUX_SENSOR, "120", attributes)
        errors = _validate_global_options(hass, {CONF_GLOBAL_LIGHT_SENSOR: LUX_SENSOR})
        if expected is None:
            assert errors == {}, name
        else:
            assert errors == {CONF_GLOBAL_LIGHT_SENSOR: expected}, name
