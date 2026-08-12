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
    CONF_ENVIRONMENT_COMFORT_MAX,
    CONF_ENVIRONMENT_COMFORT_MIN,
    CONF_ENVIRONMENT_OUTDOOR_HUMIDITY,
    CONF_ENVIRONMENT_OUTDOOR_TEMPERATURE,
    CONF_ENVIRONMENT_SURFACE_TEMPERATURE,
    CONF_ENVIRONMENT_WINDOWS,
    CONF_EXCLUDE_ENTITIES,
    CONF_FEATURE_FAN_GROUPS,
    CONF_FEATURE_ENVIRONMENT,
    CONF_FEATURE_HEALTH,
    CONF_ID,
    CONF_NAME,
    CONF_ROOM_CATEGORY,
    CONF_TRACK_ROOM_USAGE,
    CONF_TYPE,
    AREA_TYPE_INTERIOR,
    AREA_TYPE_EXTERIOR,
    AirQualityState,
    CirculationFanRequest,
    CleaningRecommendation,
    ComfortState,
    CoolingState,
    EnvironmentState,
    HumidityState,
    MouldRiskState,
    RoomUsageState,
    RoomCategory,
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
            CONF_ENABLED_FEATURES: {},
            CONF_TRACK_ROOM_USAGE: track_room_usage,
            **(feature_config or {}),
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
    assert engine.assessment["comfort_confidence"] == "basic"


def test_temperature_and_humidity_produce_derived_comfort(
    hass: HomeAssistant,
) -> None:
    """Temperature plus humidity yields enhanced psychrometric values."""
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

    assert assessment["comfort_confidence"] == "enhanced"
    assert assessment["dew_point"] == 22.01
    assert assessment["absolute_humidity"] > 18
    assert assessment["humidity_ratio"] > 10
    assert assessment["enthalpy"] > 50
    assert assessment["humidex"] > assessment["temperature"]
    assert (
        assessment["source_entities"]["humidity"]["entities"][0]["entity_id"]
        == "sensor.humidity"
    )


def test_psychrometric_reference_calculations() -> None:
    """Published moist-air approximations remain numerically stable at 20 °C/50%."""
    assert round(AreaEnvironmentEngine._dew_point(20, 50), 2) == 9.26
    assert round(AreaEnvironmentEngine._absolute_humidity(20, 50), 2) == 8.62
    assert round(AreaEnvironmentEngine._humidity_ratio(20, 50), 2) == 7.24
    assert round(AreaEnvironmentEngine._enthalpy(20, 50), 2) == 38.50


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
    assert engine.assessment["ventilation"] == VentilationState.RECOMMENDED
    assert engine.assessment["window_recommendation"] == WindowRecommendation.OPEN
    assert engine.assessment["ventilation_fan_request"] == VentilationFanRequest.LOW

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
    """A shower-like peak cannot claim persistent mould risk."""
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
    assert engine.assessment["mould_risk"] == MouldRiskState.LOW

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
    hass: HomeAssistant, freezer
) -> None:
    """Limited PM coverage stays unknown and never requests outdoor ventilation."""
    area = _area(hass)
    _sensor(hass, area, "sensor.co2", 800, SensorDeviceClass.CO2, "ppm")
    _sensor(hass, area, "sensor.pm25", 80, SensorDeviceClass.PM25, "µg/m³")
    engine = AreaEnvironmentEngine(area)
    assessment = engine.assessment

    assert assessment["air_quality"] == AirQualityState.UNKNOWN
    assert assessment["pollutant_assessments"]["pm25"]["quality"] == "limited"
    assert assessment["source_entities"]["pm25"]["entities"][0]["entity_id"] == (
        "sensor.pm25"
    )
    assert assessment["ventilation"] == VentilationState.NOT_REQUIRED
    assert assessment["ventilation_fan_request"] == VentilationFanRequest.NONE

    freezer.tick(18 * 60 * 60)
    engine.evaluate()
    assert engine.assessment["air_quality"] == AirQualityState.CRITICAL
    assert engine.assessment["ventilation_fan_request"] == VentilationFanRequest.NONE
    assert "high_pm25" in engine.assessment["reason_codes"]


def test_pollutant_unit_must_match_matrix(hass: HomeAssistant) -> None:
    """A device class with incompatible units is ignored safely."""
    area = _area(hass)
    _sensor(hass, area, "sensor.pm25", 80, SensorDeviceClass.PM25, "ppm")
    assessment = AreaEnvironmentEngine(area).assessment

    assert assessment["air_quality"] == AirQualityState.UNKNOWN
    assert assessment["capabilities"]["pm25"] is False


def test_pm_uses_observed_rolling_day(hass: HomeAssistant, freezer) -> None:
    """PM uses elapsed-time weighting, coverage quality, and a 24-hour window."""
    area = _area(hass)
    _sensor(hass, area, "sensor.pm25", 10, SensorDeviceClass.PM25, "µg/m³")
    engine = AreaEnvironmentEngine(area)
    assert engine.assessment["air_quality"] == AirQualityState.UNKNOWN
    assert engine.assessment["pollutant_assessments"]["pm25"] == {
        "current": 10.0,
        "rolling_24h": None,
        "coverage_hours": 0.0,
        "quality": "limited",
        "basis": "WHO-24h",
        "basis_type": "scientific_guideline",
    }

    freezer.tick(6 * 60 * 60)

    hass.states.async_set(
        "sensor.pm25",
        "80",
        {
            ATTR_DEVICE_CLASS: SensorDeviceClass.PM25,
            ATTR_UNIT_OF_MEASUREMENT: "µg/m³",
        },
    )
    engine.evaluate()
    assert engine.assessment["air_quality"] == AirQualityState.UNKNOWN

    freezer.tick(18 * 60 * 60)
    engine.evaluate()
    assert engine.assessment["pollutants"]["pm25"] == 80
    assert engine.assessment["pollutant_assessments"]["pm25"]["rolling_24h"] == 62.5
    assert engine.assessment["pollutant_assessments"]["pm25"]["coverage_hours"] == 24
    assert engine.assessment["air_quality"] == AirQualityState.POOR

    freezer.tick(24 * 60 * 60)
    engine.evaluate()
    assert engine.assessment["pollutant_assessments"]["pm25"]["rolling_24h"] == 80
    assert engine.assessment["air_quality"] == AirQualityState.CRITICAL


def test_surface_temperature_improves_mould_quality(
    hass: HomeAssistant, freezer
) -> None:
    """A measured cool surface drives surface-RH persistence evaluation."""
    area = _area(
        hass,
        {CONF_ENVIRONMENT_SURFACE_TEMPERATURE: "sensor.cool_wall"},
    )
    _sensor(
        hass,
        area,
        "sensor.room_temperature",
        22,
        SensorDeviceClass.TEMPERATURE,
        UnitOfTemperature.CELSIUS,
    )
    _sensor(hass, area, "sensor.humidity", 55, SensorDeviceClass.HUMIDITY, "%")
    hass.states.async_set(
        "sensor.cool_wall",
        "14",
        {
            ATTR_DEVICE_CLASS: SensorDeviceClass.TEMPERATURE,
            ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS,
        },
    )
    area.entities["sensor"].append({ATTR_ENTITY_ID: "sensor.cool_wall"})
    engine = AreaEnvironmentEngine(area)

    assert engine.assessment["temperature"] == 22
    assert engine.assessment["mould_quality"] == "surface_based"
    assert engine.assessment["surface_relative_humidity"] > 80
    assert engine.assessment["mould_risk"] == MouldRiskState.LOW
    freezer.tick(6 * 60 * 60)
    engine.evaluate()
    assert engine.assessment["mould_risk"] == MouldRiskState.ELEVATED


def test_room_category_can_make_comfort_not_applicable(hass: HomeAssistant) -> None:
    """Storage and unconditioned Areas do not receive residential comfort labels."""
    area = _area(hass, {CONF_ROOM_CATEGORY: RoomCategory.SERVICE_STORAGE})
    _sensor(
        hass,
        area,
        "sensor.room_temperature",
        12,
        SensorDeviceClass.TEMPERATURE,
        UnitOfTemperature.CELSIUS,
    )
    assessment = AreaEnvironmentEngine(area).assessment

    assert assessment["comfort"] == ComfortState.NOT_APPLICABLE
    assert assessment["comfort_quality"] == "not_applicable"
    assert assessment["cooling"] == CoolingState.NOT_REQUIRED


def test_outdoor_moisture_can_keep_window_closed(hass: HomeAssistant) -> None:
    """Humidity advice compares moisture ratio instead of relative humidity alone."""
    area = _area(
        hass,
        {
            CONF_ENVIRONMENT_OUTDOOR_TEMPERATURE: "sensor.outdoor_temperature",
            CONF_ENVIRONMENT_OUTDOOR_HUMIDITY: "sensor.outdoor_humidity",
            CONF_ENVIRONMENT_WINDOWS: ["binary_sensor.window"],
        },
    )
    _sensor(
        hass,
        area,
        "sensor.room_temperature",
        22,
        SensorDeviceClass.TEMPERATURE,
        UnitOfTemperature.CELSIUS,
    )
    _sensor(hass, area, "sensor.humidity", 76, SensorDeviceClass.HUMIDITY, "%")
    hass.states.async_set(
        "sensor.outdoor_temperature",
        "28",
        {ATTR_DEVICE_CLASS: SensorDeviceClass.TEMPERATURE},
    )
    hass.states.async_set(
        "sensor.outdoor_humidity",
        "80",
        {ATTR_DEVICE_CLASS: SensorDeviceClass.HUMIDITY},
    )
    hass.states.async_set(
        "binary_sensor.window",
        STATE_OFF,
        {ATTR_DEVICE_CLASS: BinarySensorDeviceClass.WINDOW},
    )
    assessment = AreaEnvironmentEngine(area).assessment

    assert assessment["moisture_ventilation"] == "unfavorable"
    assert assessment["window_recommendation"] == WindowRecommendation.KEEP_CLOSED
    assert assessment["ventilation_fan_request"] == VentilationFanRequest.NONE


def test_exclusion_is_authoritative_and_sources_are_transparent(
    hass: HomeAssistant,
) -> None:
    """General exclusions remove evaluation inputs; retained sources show ID and name."""
    area = _area(
        hass,
        {
            CONF_EXCLUDE_ENTITIES: [
                "sensor.bad_temperature",
                "sensor.excluded_outdoor",
            ],
            CONF_ENVIRONMENT_OUTDOOR_TEMPERATURE: "sensor.excluded_outdoor",
        },
    )
    _sensor(
        hass,
        area,
        "sensor.bad_temperature",
        40,
        SensorDeviceClass.TEMPERATURE,
        UnitOfTemperature.CELSIUS,
    )
    hass.states.async_set(
        "sensor.excluded_outdoor",
        "10",
        {ATTR_DEVICE_CLASS: SensorDeviceClass.TEMPERATURE},
    )
    _sensor(
        hass,
        area,
        "sensor.good_temperature",
        21,
        SensorDeviceClass.TEMPERATURE,
        UnitOfTemperature.CELSIUS,
    )
    assessment = AreaEnvironmentEngine(area).assessment

    assert assessment["temperature"] == 21
    assert assessment["outdoor_temperature"] is None
    assert assessment["source_entities"]["temperature"] == {
        "mode": "direct",
        "entities": [
            {"entity_id": "sensor.good_temperature", "name": "good temperature"}
        ],
    }


async def test_late_exterior_area_refreshes_automatic_sources(
    hass: HomeAssistant,
) -> None:
    """Setup order does not prevent automatic exterior source discovery/listening."""
    interior = _area(hass)
    _sensor(
        hass,
        interior,
        "sensor.room_temperature",
        27,
        SensorDeviceClass.TEMPERATURE,
        UnitOfTemperature.CELSIUS,
    )
    engine = AreaEnvironmentEngine(interior)
    assert engine.assessment["outdoor_temperature"] is None

    exterior = _area(hass)
    exterior.config[CONF_TYPE] = AREA_TYPE_EXTERIOR
    _sensor(
        hass,
        exterior,
        "sensor.garden_temperature",
        20,
        SensorDeviceClass.TEMPERATURE,
        UnitOfTemperature.CELSIUS,
    )
    hass.data.setdefault(MODULE_DATA, {})["exterior"] = {DATA_AREA_OBJECT: exterior}
    engine._area_loaded(AREA_TYPE_EXTERIOR, None, exterior.id)

    assert engine.assessment["outdoor_temperature"] == 20
    assert engine.assessment["cooling"] == CoolingState.PASSIVE_RECOMMENDED
    hass.states.async_set(
        "sensor.garden_temperature",
        "30",
        {
            ATTR_DEVICE_CLASS: SensorDeviceClass.TEMPERATURE,
            ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS,
        },
    )
    await hass.async_block_till_done()
    assert engine.assessment["outdoor_temperature"] == 30


def test_tvoc_mass_is_precaution_only_and_generic_scale_is_unclassified(
    hass: HomeAssistant,
) -> None:
    """TVOC mass uses AIR precaution; generic VOC ppb is never toxicologically mapped."""
    area = _area(hass)
    _sensor(
        hass,
        area,
        "sensor.tvoc",
        951,
        SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS,
        "µg/m³",
    )
    _sensor(
        hass,
        area,
        "sensor.voc_parts",
        5000,
        SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS_PARTS,
        "ppb",
    )
    assessment = AreaEnvironmentEngine(area).assessment

    assert assessment["air_quality"] == AirQualityState.DEGRADED
    assert assessment["pollutant_assessments"]["voc"]["quality"] == (
        "precaution_indicator"
    )
    assert assessment["pollutant_assessments"]["voc_parts"]["quality"] == (
        "unsupported_scale"
    )


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

    assert assessment["context"].startswith("Lüften empfohlen")
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


async def test_room_usage_is_exposed_by_intrinsic_area_evaluation(
    hass: HomeAssistant,
) -> None:
    """The basic usage opt-in is exposed by intrinsic Area Evaluation."""
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


async def test_regular_interior_always_creates_area_evaluation_sensor(
    hass: HomeAssistant,
) -> None:
    """Regular indoor Areas receive evaluation even with no optional features."""
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    data[CONF_ENABLED_FEATURES] = {}
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    await init_integration(hass, [entry])

    area = hass.data[MODULE_DATA][entry.entry_id][DATA_AREA_OBJECT]
    assert area.environment is not None
    state = hass.states.get(f"sensor.adaptive_areas_environment_{DEFAULT_MOCK_AREA}")
    assert state is not None
    assert state.state == EnvironmentState.UNKNOWN

    await shutdown_integration(hass, [entry])


async def test_regular_exterior_does_not_create_area_evaluation_sensor(
    hass: HomeAssistant,
) -> None:
    """Exterior Areas provide outdoor sources but receive no indoor evaluation."""
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    data[CONF_TYPE] = AREA_TYPE_EXTERIOR
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    await init_integration(hass, [entry])

    area = hass.data[MODULE_DATA][entry.entry_id][DATA_AREA_OBJECT]
    assert area.environment is None
    assert (
        hass.states.get(f"sensor.adaptive_areas_environment_{DEFAULT_MOCK_AREA}")
        is None
    )

    await shutdown_integration(hass, [entry])


async def test_rc4_environment_config_migrates_to_intrinsic_evaluation(
    hass: HomeAssistant,
) -> None:
    """RC4 feature settings migrate safely; obsolete manual bands are dropped."""
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    data[CONF_ENABLED_FEATURES] = {
        CONF_FEATURE_ENVIRONMENT: {
            CONF_ENVIRONMENT_COMFORT_MIN: 19,
            CONF_ENVIRONMENT_COMFORT_MAX: 25,
            CONF_ENVIRONMENT_OUTDOOR_TEMPERATURE: "sensor.outdoor",
            CONF_ENVIRONMENT_CIRCULATION_FANS: ["fan.room"],
        }
    }
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=data,
        options={
            CONF_ENABLED_FEATURES: {
                CONF_FEATURE_ENVIRONMENT: {
                    CONF_ENVIRONMENT_COMFORT_MIN: 18,
                    CONF_ENVIRONMENT_WINDOWS: ["binary_sensor.window"],
                }
            }
        },
        version=2,
        minor_version=2,
    )
    await init_integration(hass, [entry])

    assert entry.minor_version == 3
    assert CONF_FEATURE_ENVIRONMENT not in entry.data[CONF_ENABLED_FEATURES]
    assert entry.data[CONF_ENVIRONMENT_OUTDOOR_TEMPERATURE] == "sensor.outdoor"
    assert entry.data[CONF_ENVIRONMENT_CIRCULATION_FANS] == ["fan.room"]
    assert CONF_ENVIRONMENT_COMFORT_MIN not in entry.data
    assert CONF_ENVIRONMENT_COMFORT_MAX not in entry.data
    assert entry.data[CONF_ROOM_CATEGORY] == RoomCategory.LIVING_SEDENTARY
    assert CONF_FEATURE_ENVIRONMENT not in entry.options[CONF_ENABLED_FEATURES]
    assert entry.options[CONF_ENVIRONMENT_WINDOWS] == ["binary_sensor.window"]
    assert CONF_ENVIRONMENT_COMFORT_MIN not in entry.options

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
        CONF_FEATURE_FAN_GROUPS: {},
    }
    data[CONF_ENVIRONMENT_CIRCULATION_FANS] = [fan.entity_id]
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
        "comfort_confidence": {"enhanced", "basic", "not_applicable", "unknown"},
        "comfort_quality": {"enhanced", "basic", "not_applicable", "unknown"},
        "room_category": {str(category) for category in RoomCategory} | {"unknown"},
        "humidity": {str(state) for state in HumidityState},
        "mould_risk": {str(state) for state in MouldRiskState},
        "mould_quality": {"surface_based", "room_air_estimate", "unknown"},
        "air_quality": {str(state) for state in AirQualityState},
        "ventilation": {str(state) for state in VentilationState},
        "cooling": {str(state) for state in CoolingState},
        "window_recommendation": {str(state) for state in WindowRecommendation},
        "ventilation_fan_request": {str(state) for state in VentilationFanRequest},
        "circulation_fan_request": {str(state) for state in CirculationFanRequest},
        "room_usage": {str(state) for state in RoomUsageState},
        "cleaning_recommendation": {str(state) for state in CleaningRecommendation},
        "moisture_ventilation": {"favorable", "unfavorable", "unknown"},
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
            "outdoor_humidity",
            "surface_temperature",
            "room_usage",
            "health",
        },
    }
    named_only = {
        "temperature",
        "relative_humidity",
        "dew_point",
        "absolute_humidity",
        "humidity_ratio",
        "enthalpy",
        "humidex",
        "apparent_temperature",
        "thermal_profile",
        "surface_temperature",
        "surface_relative_humidity",
        "mould_warning_duration_seconds",
        "outdoor_temperature",
        "outdoor_relative_humidity",
        "outdoor_humidity_ratio",
        "outdoor_enthalpy",
        "pollutant_measurements",
        "pollutant_assessments",
        "source_entities",
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
