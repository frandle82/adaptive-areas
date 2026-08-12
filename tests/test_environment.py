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
    CONF_FEATURE_HEALTH,
    CONF_ID,
    CONF_NAME,
    CONF_TRACK_ROOM_USAGE,
    CONF_TYPE,
    AREA_TYPE_INTERIOR,
    AirQualityState,
    CirculationFanRequest,
    CleaningRecommendation,
    ComfortState,
    CoolingState,
    EnvironmentState,
    HumidityState,
    MouldRiskState,
    RoomUsageState,
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


def _area(
    hass: HomeAssistant,
    feature_config: dict | None = None,
    *,
    environment: bool = True,
    track_room_usage: bool = False,
) -> AdaptiveArea:
    """Return a minimally initialized regular area."""
    config_entry = MockConfigEntry(
        domain="adaptive_areas",
        data={
            CONF_ID: "kitchen",
            CONF_NAME: "Kitchen",
            CONF_TYPE: AREA_TYPE_INTERIOR,
            CONF_ENABLED_FEATURES: (
                {CONF_FEATURE_ENVIRONMENT: feature_config or {}} if environment else {}
            ),
            CONF_TRACK_ROOM_USAGE: track_room_usage,
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
    assert engine.assessment["comfort_confidence"] == "limited"


def test_temperature_and_humidity_produce_derived_comfort(
    hass: HomeAssistant,
) -> None:
    """Temperature plus humidity yields full-confidence derived values."""
    area = _area(hass)
    _sensor(
        hass,
        area,
        "sensor.room_temperature",
        28,
        SensorDeviceClass.TEMPERATURE,
        UnitOfTemperature.CELSIUS,
    )
    _sensor(hass, area, "sensor.humidity", 70, SensorDeviceClass.HUMIDITY, "%")
    assessment = AreaEnvironmentEngine(area).assessment

    assert assessment["comfort_confidence"] == "full"
    assert assessment["dew_point"] == 22.01
    assert assessment["apparent_temperature"] > assessment["temperature"]


def test_humidity_only_cannot_infer_comfort(hass: HomeAssistant) -> None:
    """Humidity alone does not become a thermal or mould assessment."""
    area = _area(hass)
    _sensor(hass, area, "sensor.humidity", 50, SensorDeviceClass.HUMIDITY, "%")
    assessment = AreaEnvironmentEngine(area).assessment

    assert assessment["comfort"] == ComfortState.UNKNOWN
    assert assessment["mould_risk"] == MouldRiskState.UNKNOWN
    assert assessment["air_quality"] == AirQualityState.UNKNOWN


def test_fahrenheit_temperature_is_converted(hass: HomeAssistant) -> None:
    """Home Assistant temperature units are normalized to Celsius."""
    area = _area(hass)
    _sensor(
        hass,
        area,
        "sensor.room_temperature",
        77,
        SensorDeviceClass.TEMPERATURE,
        UnitOfTemperature.FAHRENHEIT,
    )
    assessment = AreaEnvironmentEngine(area).assessment

    assert assessment["temperature"] == 25
    assert assessment["comfort"] == ComfortState.WARM


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


def test_persistent_humidity_increases_mould_risk(hass: HomeAssistant, freezer) -> None:
    """Mould risk needs sustained moisture and remains an indicator only."""
    area = _area(hass)
    _sensor(
        hass,
        area,
        "sensor.room_temperature",
        22,
        SensorDeviceClass.TEMPERATURE,
        UnitOfTemperature.CELSIUS,
    )
    _sensor(hass, area, "sensor.humidity", 72, SensorDeviceClass.HUMIDITY, "%")
    engine = AreaEnvironmentEngine(area)
    assert engine.assessment["mould_risk"] == MouldRiskState.LOW

    freezer.tick(6 * 60 * 60)
    engine.evaluate()
    assert engine.assessment["mould_risk"] == MouldRiskState.ELEVATED

    freezer.tick(18 * 60 * 60)
    engine.evaluate()
    assert engine.assessment["mould_risk"] == MouldRiskState.HIGH
    assert "not mould detection" in engine.assessment["context"]


def test_short_humidity_peak_recovers_without_high_mould_risk(
    hass: HomeAssistant,
) -> None:
    """A shower-like peak may elevate risk but cannot claim persistent high risk."""
    area = _area(hass)
    _sensor(
        hass,
        area,
        "sensor.room_temperature",
        22,
        SensorDeviceClass.TEMPERATURE,
        UnitOfTemperature.CELSIUS,
    )
    _sensor(hass, area, "sensor.humidity", 80, SensorDeviceClass.HUMIDITY, "%")
    engine = AreaEnvironmentEngine(area)
    assert engine.assessment["mould_risk"] == MouldRiskState.ELEVATED

    hass.states.async_set(
        "sensor.humidity",
        "55",
        {
            ATTR_DEVICE_CLASS: SensorDeviceClass.HUMIDITY,
            ATTR_UNIT_OF_MEASUREMENT: "%",
        },
    )
    engine.evaluate()
    assert engine.assessment["mould_risk"] == MouldRiskState.LOW


def test_worst_pollutant_does_not_request_ventilation_fan(
    hass: HomeAssistant,
) -> None:
    """PM drives air-quality severity but not the separate ventilation model."""
    area = _area(hass)
    _sensor(hass, area, "sensor.co2", 800, SensorDeviceClass.CO2, "ppm")
    _sensor(hass, area, "sensor.pm25", 80, SensorDeviceClass.PM25, "µg/m³")
    assessment = AreaEnvironmentEngine(area).assessment

    assert assessment["air_quality"] == AirQualityState.CRITICAL
    assert assessment["ventilation"] == VentilationState.NOT_REQUIRED
    assert assessment["ventilation_fan_request"] == VentilationFanRequest.NONE
    assert "high_pm25" in assessment["reason_codes"]


def test_pollutant_unit_must_match_matrix(hass: HomeAssistant) -> None:
    """A device class with incompatible units is ignored safely."""
    area = _area(hass)
    _sensor(hass, area, "sensor.pm25", 80, SensorDeviceClass.PM25, "ppm")
    assessment = AreaEnvironmentEngine(area).assessment

    assert assessment["air_quality"] == AirQualityState.UNKNOWN
    assert assessment["capabilities"]["pm25"] is False


def test_pm_uses_observed_rolling_day(hass: HomeAssistant, freezer) -> None:
    """PM uses retained observations and safely expires a constant old sample."""
    area = _area(hass)
    _sensor(hass, area, "sensor.pm25", 10, SensorDeviceClass.PM25, "µg/m³")
    engine = AreaEnvironmentEngine(area)
    assert engine.assessment["air_quality"] == AirQualityState.GOOD

    hass.states.async_set(
        "sensor.pm25",
        "80",
        {
            ATTR_DEVICE_CLASS: SensorDeviceClass.PM25,
            ATTR_UNIT_OF_MEASUREMENT: "µg/m³",
        },
    )
    engine.evaluate()
    assert engine.assessment["air_quality"] == AirQualityState.POOR

    freezer.tick(24 * 60 * 60 + 1)
    engine.evaluate()
    assert engine.assessment["pollutants"]["pm25"] == 80
    assert engine.assessment["air_quality"] == AirQualityState.CRITICAL


def test_room_usage_uses_presence_transitions_only(
    hass: HomeAssistant, freezer
) -> None:
    """Opt-in usage records sessions and recommends cleaning after clearing."""
    area = _area(hass, environment=False, track_room_usage=True)
    engine = AreaEnvironmentEngine(area)
    assert engine.assessment["room_usage"] == RoomUsageState.UNUSED
    assert (
        engine.assessment["cleaning_recommendation"] == CleaningRecommendation.ALLOWED
    )

    area.states = ["occupied"]
    engine._area_state_changed(area.id, None)
    assert len(area.decision_trace.export()) == 1
    freezer.tick(2 * 60 * 60)
    engine.evaluate()
    assert len(area.decision_trace.export()) == 1
    assert engine.assessment["room_usage"] == RoomUsageState.HIGH
    assert (
        engine.assessment["cleaning_recommendation"] == CleaningRecommendation.POSTPONE
    )

    area.states = ["clear"]
    engine._area_state_changed(area.id, None)
    assert (
        engine.assessment["cleaning_recommendation"] == CleaningRecommendation.PREFERRED
    )
    assert len(area.decision_trace.export()) == 2
    assert "cleaning_preferred_room_clear" in (
        area.decision_trace.export()[-1]["reason_codes"]
    )
    assert "cleaning" in engine.assessment["context"].lower()


def test_health_warning_has_highest_context_priority(hass: HomeAssistant) -> None:
    """An existing Area Health warning outranks environmental advice."""
    area = _area(hass)
    area.config[CONF_ENABLED_FEATURES][CONF_FEATURE_HEALTH] = {}
    hass.states.async_set("binary_sensor.adaptive_areas_health_kitchen", STATE_ON)
    _sensor(hass, area, "sensor.co2", 2200, SensorDeviceClass.CO2, "ppm")
    assessment = AreaEnvironmentEngine(area).assessment

    assert assessment["health_alert"] is True
    assert assessment["dominant_decision"] == "health_alert"
    assert assessment["reason_codes"][-1] == "health_alert"


def test_german_context_is_human_readable(hass: HomeAssistant) -> None:
    """Context renders localized prose while reasons remain stable."""
    hass.config.language = "de"
    area = _area(hass)
    _sensor(hass, area, "sensor.co2", 1500, SensorDeviceClass.CO2, "ppm")
    assessment = AreaEnvironmentEngine(area).assessment

    assert assessment["context"].startswith("Lüften erforderlich")
    assert "high_co2" in assessment["reason_codes"]


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


async def test_room_usage_alone_creates_environment_sensor(
    hass: HomeAssistant,
) -> None:
    """The basic opt-in works without enabling Environment Monitoring."""
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    data[CONF_TRACK_ROOM_USAGE] = True
    data[CONF_ENABLED_FEATURES] = {}
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    await init_integration(hass, [entry])

    area = hass.data[MODULE_DATA][entry.entry_id][DATA_AREA_OBJECT]
    assert area.environment is not None
    state = hass.states.get(f"sensor.adaptive_areas_environment_{DEFAULT_MOCK_AREA}")
    assert state is not None
    assert state.attributes["room_usage"] == RoomUsageState.UNUSED
    assert state.attributes["cleaning_recommendation"] == (
        CleaningRecommendation.ALLOWED
    )

    await shutdown_integration(hass, [entry])


async def test_room_usage_disabled_creates_no_environment_sensor(
    hass: HomeAssistant,
) -> None:
    """Backwards-compatible defaults add no usage runtime or entity."""
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    data[CONF_ENABLED_FEATURES] = {}
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    await init_integration(hass, [entry])

    area = hass.data[MODULE_DATA][entry.entry_id][DATA_AREA_OBJECT]
    assert area.environment is None
    assert (
        hass.states.get(f"sensor.adaptive_areas_environment_{DEFAULT_MOCK_AREA}")
        is None
    )

    await shutdown_integration(hass, [entry])


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
    environment_state = hass.states.get(environment_entity_id)
    assert environment_state is not None
    assert environment_state.attributes["decision_context"] == ["room_too_warm"]
    assert environment_state.attributes["reason_codes"] == ["room_too_warm"]
    assert environment_state.attributes["context"]

    await shutdown_integration(hass, [entry])


def test_environment_translation_value_coverage() -> None:
    """English and German translate every Environment state and attribute value."""
    translations = Path("custom_components/adaptive_areas/translations")
    expected_values = {
        "comfort": {str(state) for state in ComfortState},
        "comfort_confidence": {"full", "limited", "unknown"},
        "humidity": {str(state) for state in HumidityState},
        "mould_risk": {str(state) for state in MouldRiskState},
        "air_quality": {str(state) for state in AirQualityState},
        "ventilation": {str(state) for state in VentilationState},
        "cooling": {str(state) for state in CoolingState},
        "window_recommendation": {str(state) for state in WindowRecommendation},
        "ventilation_fan_request": {str(state) for state in VentilationFanRequest},
        "circulation_fan_request": {str(state) for state in CirculationFanRequest},
        "room_usage": {str(state) for state in RoomUsageState},
        "cleaning_recommendation": {str(state) for state in CleaningRecommendation},
        "available_capabilities": {
            "temperature",
            "humidity",
            "co2",
            "pm25",
            "pm10",
            "voc",
            "aqi",
            "co",
            "no2",
            "windows",
            "outdoor_temperature",
            "room_usage",
            "health",
        },
    }
    named_only = {
        "temperature",
        "relative_humidity",
        "dew_point",
        "apparent_temperature",
        "pollutant_measurements",
        "current_occupancy_duration",
        "occupied_duration_today",
        "occupancy_sessions_today",
        "time_since_last_occupancy",
        "humidity_warning_duration_seconds",
        "last_occupied",
        "last_cleared",
        "context",
    }

    for language in ("en", "de"):
        content = json.loads((translations / f"{language}.json").read_text())
        environment = content["entity"]["sensor"]["environment"]
        assert set(environment["state"]) == {str(state) for state in EnvironmentState}
        assert set(expected_values) | named_only <= set(environment["state_attributes"])
        for attribute, values in expected_values.items():
            translation = environment["state_attributes"][attribute]
            assert translation["name"]
            assert set(translation["state"]) == values
            assert all(translation["state"].values())
