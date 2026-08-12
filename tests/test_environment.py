"""Tests for the capability-aware Area Environment Engine."""

import json
from pathlib import Path
from types import SimpleNamespace

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_ENTITY_ID,
    ATTR_UNIT_OF_MEASUREMENT,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant

from custom_components.adaptive_areas.base.adaptive import AdaptiveArea
from custom_components.adaptive_areas.const import (
    CONF_ENABLED_FEATURES,
    CONF_ENVIRONMENT_HUMIDITY_DURATION,
    CONF_ENVIRONMENT_CIRCULATION_FANS,
    CONF_ENVIRONMENT_OUTDOOR_TEMPERATURE,
    CONF_ENVIRONMENT_WINDOWS,
    CONF_FEATURE_ENVIRONMENT,
    CONF_FEATURE_FAN_GROUPS,
    CONF_ID,
    CONF_NAME,
    CONF_TYPE,
    AREA_TYPE_INTERIOR,
    CirculationFanRequest,
    ComfortState,
    CoolingState,
    EnvironmentState,
    HumidityState,
    VentilationFanRequest,
    VentilationState,
    WindowRecommendation,
    DATA_AREA_OBJECT,
    DOMAIN,
    MODULE_DATA,
)
from custom_components.adaptive_areas.helpers.environment import AreaEnvironmentEngine

from tests.const import DEFAULT_MOCK_AREA
from tests.helpers import (
    get_basic_config_entry_data,
    init_integration,
    setup_mock_entities,
    shutdown_integration,
)
from tests.mocks import MockFan, MockSensor


def _area(hass: HomeAssistant, feature_config: dict | None = None) -> AdaptiveArea:
    """Return a minimally initialized regular area."""
    config_entry = MockConfigEntry(
        domain="adaptive_areas",
        data={
            CONF_ID: "kitchen",
            CONF_NAME: "Kitchen",
            CONF_TYPE: AREA_TYPE_INTERIOR,
            CONF_ENABLED_FEATURES: {CONF_FEATURE_ENVIRONMENT: feature_config or {}},
        },
    )
    return AdaptiveArea(
        hass,
        SimpleNamespace(id="kitchen", name="Kitchen", icon=None, floor_id=None),
        config_entry,
    )


def _sensor(
    hass: HomeAssistant,
    area: AdaptiveArea,
    entity_id: str,
    value: float,
    device_class: SensorDeviceClass,
    unit: str | None = None,
) -> None:
    """Add an environmental sensor state to the area."""
    attributes = {ATTR_DEVICE_CLASS: device_class}
    if unit:
        attributes[ATTR_UNIT_OF_MEASUREMENT] = unit
    hass.states.async_set(entity_id, str(value), attributes)
    area.entities.setdefault("sensor", []).append({ATTR_ENTITY_ID: entity_id})


def test_temperature_only_is_partial(hass: HomeAssistant) -> None:
    """Temperature works without falsely claiming ventilation or cooling health."""
    area = _area(hass)
    _sensor(
        hass,
        area,
        "sensor.room_temperature",
        25,
        SensorDeviceClass.TEMPERATURE,
        UnitOfTemperature.CELSIUS,
    )
    engine = AreaEnvironmentEngine(area)

    assert engine.assessment["comfort"] == ComfortState.WARM
    assert engine.assessment["ventilation"] == VentilationState.UNKNOWN
    assert engine.assessment["cooling"] == CoolingState.UNKNOWN
    assert engine.assessment["state"] == EnvironmentState.ATTENTION
    assert engine.assessment["capabilities"]["co2"] is False


def test_passive_and_active_cooling(hass: HomeAssistant) -> None:
    """Outdoor comparison distinguishes passive and active cooling."""
    area = _area(
        hass,
        {
            CONF_ENVIRONMENT_OUTDOOR_TEMPERATURE: "sensor.outdoor_temperature",
            CONF_ENVIRONMENT_WINDOWS: ["binary_sensor.window"],
        },
    )
    _sensor(
        hass,
        area,
        "sensor.room_temperature",
        27,
        SensorDeviceClass.TEMPERATURE,
        UnitOfTemperature.CELSIUS,
    )
    hass.states.async_set(
        "sensor.outdoor_temperature",
        "22",
        {
            ATTR_DEVICE_CLASS: SensorDeviceClass.TEMPERATURE,
            ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS,
        },
    )
    hass.states.async_set(
        "binary_sensor.window",
        STATE_OFF,
        {ATTR_DEVICE_CLASS: BinarySensorDeviceClass.WINDOW},
    )
    engine = AreaEnvironmentEngine(area)
    assert engine.assessment["cooling"] == CoolingState.PASSIVE_RECOMMENDED
    assert engine.assessment["window_recommendation"] == WindowRecommendation.OPEN

    hass.states.async_set(
        "sensor.outdoor_temperature",
        "30",
        {
            ATTR_DEVICE_CLASS: SensorDeviceClass.TEMPERATURE,
            ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS,
        },
    )
    engine.evaluate()
    assert engine.assessment["cooling"] == CoolingState.ACTIVE_RECOMMENDED
    assert (
        engine.assessment["window_recommendation"] == WindowRecommendation.KEEP_CLOSED
    )


def test_co2_thresholds_hysteresis_and_window(hass: HomeAssistant) -> None:
    """CO2 is the primary ventilation input and clears below 850 ppm."""
    area = _area(hass, {CONF_ENVIRONMENT_WINDOWS: ["binary_sensor.window"]})
    _sensor(hass, area, "sensor.co2", 1500, SensorDeviceClass.CO2, "ppm")
    hass.states.async_set(
        "binary_sensor.window",
        STATE_OFF,
        {ATTR_DEVICE_CLASS: BinarySensorDeviceClass.WINDOW},
    )
    area.entities["binary_sensor"] = [{ATTR_ENTITY_ID: "binary_sensor.window"}]
    engine = AreaEnvironmentEngine(area)
    assert engine.assessment["ventilation"] == VentilationState.REQUIRED
    assert engine.assessment["window_recommendation"] == WindowRecommendation.OPEN
    assert engine.assessment["ventilation_fan_request"] == VentilationFanRequest.HIGH

    hass.states.async_set(
        "sensor.co2", "900", {ATTR_DEVICE_CLASS: SensorDeviceClass.CO2}
    )
    engine.evaluate()
    assert engine.assessment["ventilation"] == VentilationState.RECOMMENDED

    hass.states.async_set(
        "binary_sensor.window",
        STATE_ON,
        {ATTR_DEVICE_CLASS: BinarySensorDeviceClass.WINDOW},
    )
    engine.evaluate()
    assert engine.assessment["ventilation"] == VentilationState.VENTILATING
    assert engine.assessment["window_recommendation"] == WindowRecommendation.NONE

    hass.states.async_set(
        "sensor.co2", "800", {ATTR_DEVICE_CLASS: SensorDeviceClass.CO2}
    )
    engine.evaluate()
    assert engine.assessment["ventilation"] == VentilationState.NOT_REQUIRED
    assert engine.assessment["window_recommendation"] == WindowRecommendation.CLOSE


def test_humidity_immediate_and_duration_design(hass: HomeAssistant) -> None:
    """Very high humidity acts immediately while normal humidity remains valid."""
    area = _area(hass, {CONF_ENVIRONMENT_HUMIDITY_DURATION: 15})
    _sensor(hass, area, "sensor.humidity", 55, SensorDeviceClass.HUMIDITY, "%")
    engine = AreaEnvironmentEngine(area)
    assert engine.assessment["humidity"] == HumidityState.NORMAL
    assert engine.assessment["ventilation"] == VentilationState.UNKNOWN

    hass.states.async_set(
        "sensor.humidity", "78", {ATTR_DEVICE_CLASS: SensorDeviceClass.HUMIDITY}
    )
    engine.evaluate()
    assert engine.assessment["humidity"] == HumidityState.VERY_HIGH
    assert engine.assessment["ventilation"] == VentilationState.REQUIRED
    assert "rapid_humidity_rise" in engine.assessment["reason_codes"]


def test_circulation_request_requires_occupancy(hass: HomeAssistant) -> None:
    """Comfort fan requests never run solely for an empty warm room."""
    area = _area(hass)
    _sensor(
        hass,
        area,
        "sensor.room_temperature",
        29,
        SensorDeviceClass.TEMPERATURE,
        UnitOfTemperature.CELSIUS,
    )
    engine = AreaEnvironmentEngine(area)
    assert engine.assessment["circulation_fan_request"] == CirculationFanRequest.NONE

    area.states = ["occupied"]
    engine.evaluate()
    assert engine.assessment["circulation_fan_request"] == CirculationFanRequest.HIGH


async def test_environment_sensor_fan_request_reaches_fan_control(
    hass: HomeAssistant,
) -> None:
    """Fan Control consumes Environment requests through existing control."""
    fan = MockFan(name="room_fan", unique_id="environment_room_fan")
    temperature = MockSensor(
        name="room_temperature",
        unique_id="environment_room_temperature",
        native_value=29,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        unit_of_measurement=UnitOfTemperature.CELSIUS,
    )
    await setup_mock_entities(hass, "fan", {DEFAULT_MOCK_AREA: [fan]})
    await setup_mock_entities(hass, "sensor", {DEFAULT_MOCK_AREA: [temperature]})

    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    data[CONF_ENABLED_FEATURES] = {
        CONF_FEATURE_ENVIRONMENT: {CONF_ENVIRONMENT_CIRCULATION_FANS: [fan.entity_id]},
        CONF_FEATURE_FAN_GROUPS: {},
    }
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    await init_integration(hass, [entry])
    area = hass.data[MODULE_DATA][entry.entry_id][DATA_AREA_OBJECT]
    assert not hasattr(area, "manual_override")
    environment_entity_id = f"sensor.adaptive_areas_environment_{DEFAULT_MOCK_AREA}"
    control_entity_id = (
        f"switch.adaptive_areas_fan_groups_{DEFAULT_MOCK_AREA}_fan_control"
    )
    environment_state = hass.states.get(environment_entity_id)
    assert environment_state is not None
    assert environment_state.attributes["device_class"] == "enum"
    assert set(environment_state.attributes["options"]) == {
        str(state) for state in EnvironmentState
    }

    await hass.services.async_call(
        "switch", SERVICE_TURN_ON, {ATTR_ENTITY_ID: control_entity_id}, blocking=True
    )
    area.states = ["occupied"]
    assert area.environment is not None
    area.environment.evaluate()
    await hass.async_block_till_done()
    assert hass.states.get(fan.entity_id).state == STATE_ON

    await shutdown_integration(hass, [entry])


def test_environment_translation_value_coverage() -> None:
    """English and German translate every Environment state and attribute value."""
    translations = Path("custom_components/adaptive_areas/translations")
    expected = {
        "comfort": {str(state) for state in ComfortState},
        "humidity": {str(state) for state in HumidityState},
        "ventilation": {str(state) for state in VentilationState},
        "cooling": {str(state) for state in CoolingState},
        "window_recommendation": {str(state) for state in WindowRecommendation},
        "ventilation_fan_request": {str(state) for state in VentilationFanRequest},
        "circulation_fan_request": {str(state) for state in CirculationFanRequest},
        "available_capabilities": {
            "temperature",
            "humidity",
            "co2",
            "voc",
            "aqi",
            "windows",
            "outdoor_temperature",
        },
    }

    for language in ("en", "de"):
        content = json.loads((translations / f"{language}.json").read_text())
        environment = content["entity"]["sensor"]["environment"]
        assert set(environment["state"]) == {str(state) for state in EnvironmentState}
        assert set(environment["state_attributes"]) == set(expected)
        for attribute, values in expected.items():
            translation = environment["state_attributes"][attribute]
            assert translation["name"]
            assert set(translation["state"]) == values
            assert all(translation["state"].values())
