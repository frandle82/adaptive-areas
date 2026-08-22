"""Tests for the capability-aware Area Environment Engine."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_ENTITY_ID,
    ATTR_FRIENDLY_NAME,
    ATTR_UNIT_OF_MEASUREMENT,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    EntityCategory,
    UnitOfDensity,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.area_registry import async_get as async_get_area_registry
from homeassistant.helpers.device_registry import async_get as async_get_device_registry
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from homeassistant.util import dt as dt_util

from custom_components.adaptive_areas import (
    _migrate_primary_area_sources,
    _migrate_room_usage_feature,
)
from custom_components.adaptive_areas.base.adaptive import AdaptiveArea
from custom_components.adaptive_areas.const import (
    CONF_AREA_HUMIDITY_SENSOR,
    CONF_AREA_TEMPERATURE_SENSOR,
    CONF_ENABLED_FEATURES,
    CONF_ENVIRONMENT_HUMIDITY_DURATION,
    CONF_ENVIRONMENT_CIRCULATION_FANS,
    CONF_ENVIRONMENT_VENTILATION_FANS,
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
    CONF_FEATURE_ROOM_USAGE,
    CONF_ID,
    CONF_INCLUDE_ENTITIES,
    CONF_NAME,
    CONF_PRESENCE_MINUTES_TO_DUE,
    CONF_ROOM_CATEGORY,
    CONF_TRACK_ROOM_USAGE,
    CONF_TYPE,
    AREA_TYPE_INTERIOR,
    AREA_TYPE_EXTERIOR,
    AirCleaningRecommendation,
    AirExchangeSuitability,
    AirQualityState,
    CirculationFanRequest,
    ComfortState,
    CombinedComfortState,
    CoolingState,
    EnvironmentState,
    HumidityState,
    MouldRiskState,
    PollutantState,
    RoomCategory,
    VentilationActivity,
    VentilationDemand,
    VentilationFanRequest,
    VentilationStrategy,
    VentilationState,
    WindowRecommendation,
    DATA_AREA_OBJECT,
    DEFAULT_PRESENCE_MINUTES_TO_DUE,
    DOMAIN,
    MODULE_DATA,
    AdaptiveConfigEntryVersion,
)
from custom_components.adaptive_areas.helpers.environment import AreaEnvironmentEngine
from custom_components.adaptive_areas.helpers.room_usage import RoomUsageEngine

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
) -> AdaptiveArea:
    """Return a minimally initialized regular area."""
    config_entry = MockConfigEntry(
        domain="adaptive_areas",
        data={
            CONF_ID: "kitchen",
            CONF_NAME: "Kitchen",
            CONF_TYPE: AREA_TYPE_INTERIOR,
            CONF_ENABLED_FEATURES: (
                {CONF_FEATURE_ENVIRONMENT: {}} if environment else {}
            ),
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
    value: float | str,
    device_class: SensorDeviceClass,
    unit: str | None = None,
) -> None:
    """Add a sensor and select the first indoor temperature/RH test source."""
    attributes = {ATTR_DEVICE_CLASS: device_class}
    if unit:
        attributes[ATTR_UNIT_OF_MEASUREMENT] = unit
    hass.states.async_set(entity_id, str(value), attributes)
    area.entities.setdefault("sensor", []).append({ATTR_ENTITY_ID: entity_id})
    if device_class == SensorDeviceClass.TEMPERATURE:
        area.config.setdefault(CONF_AREA_TEMPERATURE_SENSOR, entity_id)
    elif device_class == SensorDeviceClass.HUMIDITY:
        area.config.setdefault(CONF_AREA_HUMIDITY_SENSOR, entity_id)


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
    assert engine.assessment["heat_protection_demand"] == "recommended"
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
    engine = AreaEnvironmentEngine(area)
    assessment = engine.assessment

    assert assessment["comfort_confidence"] == "enhanced"
    assert assessment["dew_point"] == 22.01
    assert assessment["absolute_humidity"] > 18
    assert assessment["humidity_ratio"] > 10
    assert assessment["enthalpy"] > 50
    assert assessment["humidex"] > assessment["temperature"]
    assert "surface_temperature" not in assessment
    assert "surface_relative_humidity" not in assessment
    assert assessment["source_entities"]["humidity"] == {
        "mode": "primary",
        "configured": True,
        "available": True,
        "entity_id": "sensor.humidity",
        "name": "humidity",
    }


def test_primary_pair_excludes_decoys_from_all_derived_physics(
    hass: HomeAssistant,
) -> None:
    """Only configured sources form the coupled indoor air state."""
    area = _area(
        hass,
        {
            CONF_AREA_TEMPERATURE_SENSOR: "sensor.primary_temperature",
            CONF_AREA_HUMIDITY_SENSOR: "sensor.primary_humidity",
        },
    )
    _sensor(
        hass,
        area,
        "sensor.primary_temperature",
        20,
        SensorDeviceClass.TEMPERATURE,
        UnitOfTemperature.CELSIUS,
    )
    _sensor(hass, area, "sensor.primary_humidity", 50, SensorDeviceClass.HUMIDITY, "%")
    _sensor(
        hass,
        area,
        "sensor.decoy_temperature",
        80,
        SensorDeviceClass.TEMPERATURE,
        UnitOfTemperature.CELSIUS,
    )
    _sensor(hass, area, "sensor.decoy_humidity", 5, SensorDeviceClass.HUMIDITY, "%")
    engine = AreaEnvironmentEngine(area)

    assert engine.assessment["temperature"] == 20
    assert engine.assessment["relative_humidity"] == 50
    assert engine.assessment["dew_point"] == 9.26
    assert engine.assessment["absolute_humidity"] == 8.62
    assert engine.assessment["humidity_ratio"] == 7.24
    assert engine.assessment["enthalpy"] == 38.5
    assert engine.assessment["thermal_input_quality"] == "enhanced"
    assert engine.assessment["air_quality"] == AirQualityState.UNKNOWN
    assert engine.assessment["state"] == EnvironmentState.GOOD

    hass.states.async_set(
        "sensor.decoy_temperature",
        "-40",
        {ATTR_DEVICE_CLASS: SensorDeviceClass.TEMPERATURE},
    )
    hass.states.async_set(
        "sensor.decoy_humidity", "100", {ATTR_DEVICE_CLASS: SensorDeviceClass.HUMIDITY}
    )
    engine.evaluate()
    assert engine.assessment["temperature"] == 20
    assert engine.assessment["relative_humidity"] == 50


def test_unavailable_primary_never_falls_back(hass: HomeAssistant) -> None:
    """Configured identity survives outage while decoys remain ignored."""
    area = _area(
        hass,
        {CONF_AREA_TEMPERATURE_SENSOR: "sensor.primary_temperature"},
    )
    _sensor(
        hass,
        area,
        "sensor.primary_temperature",
        21,
        SensorDeviceClass.TEMPERATURE,
        UnitOfTemperature.CELSIUS,
    )
    _sensor(
        hass,
        area,
        "sensor.decoy_temperature",
        30,
        SensorDeviceClass.TEMPERATURE,
        UnitOfTemperature.CELSIUS,
    )
    engine = AreaEnvironmentEngine(area)
    hass.states.async_set(
        "sensor.primary_temperature",
        STATE_UNAVAILABLE,
        {ATTR_DEVICE_CLASS: SensorDeviceClass.TEMPERATURE},
    )
    engine.evaluate()

    assert engine.assessment["temperature"] is None
    assert engine.assessment["comfort"] == ComfortState.UNKNOWN
    assert engine.assessment["heat_protection_demand"] == "unknown"
    assert engine.assessment["thermal_input_quality"] == "unavailable"
    assert engine.assessment["source_entities"]["temperature"]["entity_id"] == (
        "sensor.primary_temperature"
    )
    assert not engine.assessment["source_entities"]["temperature"]["available"]


def test_missing_climate_sources_do_not_disable_co2(hass: HomeAssistant) -> None:
    """Independent CO2 safety and ventilation survive absent climate sources."""
    area = _area(hass)
    _sensor(hass, area, "sensor.co2", 2200, SensorDeviceClass.CO2, "ppm")
    assessment = AreaEnvironmentEngine(area).assessment

    assert assessment["temperature"] is None
    assert assessment["relative_humidity"] is None
    assert assessment["air_quality"] == AirQualityState.CRITICAL
    assert assessment["ventilation"] == VentilationState.URGENT
    assert assessment["dominant_decision"] == "air_quality_critical"
    assert "CO₂" in assessment["context"]
    assert "primary_temperature_sensor_not_configured" in assessment["reason_codes"]


def test_absent_pollutants_do_not_create_phantom_assessments(
    hass: HomeAssistant,
) -> None:
    """Unmeasured rolling pollutants neither appear nor poison valid CO2."""
    area = _area(hass)
    _sensor(hass, area, "sensor.co2", 800, SensorDeviceClass.CO2, "ppm")
    engine = AreaEnvironmentEngine(area)
    assessment = engine.assessment

    assert assessment["air_quality"] == AirQualityState.GOOD
    assert assessment["pollutants"] == {"co2": 800.0}
    assert set(assessment["pollutant_assessments"]) == {"co2"}
    for absent in ("pm25", "pm10", "no2", "co", "voc"):
        assert absent not in assessment["pollutants"]
        assert absent not in assessment["pollutant_assessments"]
        assert absent not in assessment["source_entities"]
    assert engine.diagnostics()["pollutant_sources"] == {"co2": 1}


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
    """Windows and fans enable passive and active cooling recommendations."""
    hass.config.language = "de"
    area = _area(
        hass,
        {
            CONF_ENVIRONMENT_OUTDOOR_TEMPERATURE: "sensor.outdoor_temperature",
            CONF_ENVIRONMENT_WINDOWS: ["binary_sensor.window"],
            CONF_ENVIRONMENT_VENTILATION_FANS: ["fan.ventilation"],
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
        "binary_sensor.window",
        STATE_ON,
        {ATTR_DEVICE_CLASS: BinarySensorDeviceClass.WINDOW},
    )
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
    assert engine.assessment["window_recommendation"] == WindowRecommendation.CLOSE
    assert "ventilation_should_stop" in engine.assessment["reason_codes"]
    assert "outdoor_air_warmer" in engine.assessment["reason_codes"]
    assert engine.assessment["context"] == (
        "Fenster schließen: Die Außenluft ist inzwischen wärmer und würde den Bereich "
        "zusätzlich aufheizen."
    )

    hass.states.async_set(
        "binary_sensor.window",
        STATE_OFF,
        {ATTR_DEVICE_CLASS: BinarySensorDeviceClass.WINDOW},
    )
    engine.evaluate()
    assert (
        engine.assessment["window_recommendation"] == WindowRecommendation.KEEP_CLOSED
    )
    assert "window_should_remain_closed" in engine.assessment["reason_codes"]
    assert engine.assessment["context"] == (
        "Fenster geschlossen halten: Die Außenluft ist derzeit wärmer und würde den "
        "Bereich zusätzlich aufheizen."
    )


def test_co2_thresholds_hysteresis_and_window(hass: HomeAssistant) -> None:
    """CO2 emits abstract ventilation and window requests without fan entities."""
    hass.config.language = "de"
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
    assert engine.assessment["ventilation_demand"] == VentilationDemand.RECOMMENDED
    assert engine.assessment["ventilation_activity"] == VentilationActivity.INACTIVE
    assert engine.assessment["window_recommendation"] == WindowRecommendation.OPEN
    assert engine.assessment["ventilation_fan_request"] == VentilationFanRequest.LOW
    assert engine.assessment["context"] == (
        "Die CO₂-Konzentration ist erhöht. Luftaustausch wird empfohlen."
    )

    hass.states.async_set(
        "sensor.co2",
        "900",
        {
            ATTR_DEVICE_CLASS: SensorDeviceClass.CO2,
            ATTR_UNIT_OF_MEASUREMENT: "ppm",
        },
    )
    engine.evaluate()
    assert engine.assessment["ventilation"] == VentilationState.RECOMMENDED

    hass.states.async_set(
        "binary_sensor.window",
        STATE_ON,
        {ATTR_DEVICE_CLASS: BinarySensorDeviceClass.WINDOW},
    )
    engine.evaluate()
    assert engine.assessment["ventilation"] == VentilationState.RECOMMENDED
    assert engine.assessment["ventilation_demand"] == VentilationDemand.RECOMMENDED
    assert engine.assessment["ventilation_activity"] == VentilationActivity.VENTILATING
    assert engine.assessment["window_recommendation"] == WindowRecommendation.NONE
    assert engine.assessment["context"] == (
        "Weiter lüften: Die CO₂-Konzentration liegt weiterhin über der "
        "Entwarnungsschwelle."
    )

    hass.states.async_set(
        "sensor.co2",
        "800",
        {
            ATTR_DEVICE_CLASS: SensorDeviceClass.CO2,
            ATTR_UNIT_OF_MEASUREMENT: "ppm",
        },
    )
    engine.evaluate()
    assert engine.assessment["ventilation"] == VentilationState.NOT_REQUIRED
    assert engine.assessment["window_recommendation"] == WindowRecommendation.CLOSE
    assert "ventilation_complete" in engine.assessment["reason_codes"]
    assert "ventilation_should_stop" not in engine.assessment["reason_codes"]
    assert engine.assessment["context"] == (
        "Lüften beenden und Fenster schließen: Die Lüftung ist nicht mehr "
        "erforderlich."
    )


def test_urgent_co2_context_reflects_current_ventilation_activity(
    hass: HomeAssistant,
) -> None:
    """Urgent CO2 demand remains urgent while an open window changes the action."""
    hass.config.language = "de"
    area = _area(hass, {CONF_ENVIRONMENT_WINDOWS: ["binary_sensor.window"]})
    _sensor(hass, area, "sensor.co2", 2200, SensorDeviceClass.CO2, "ppm")
    hass.states.async_set(
        "binary_sensor.window",
        STATE_OFF,
        {ATTR_DEVICE_CLASS: BinarySensorDeviceClass.WINDOW},
    )
    engine = AreaEnvironmentEngine(area)

    assert engine.assessment["ventilation_demand"] == VentilationDemand.URGENT
    assert engine.assessment["ventilation_activity"] == VentilationActivity.INACTIVE
    assert engine.assessment["window_recommendation"] == WindowRecommendation.OPEN
    assert engine.assessment["context"] == (
        "Die CO₂-Konzentration im Raum ist sehr hoch. Luftaustausch ist dringend "
        "erforderlich."
    )

    hass.states.async_set(
        "binary_sensor.window",
        STATE_ON,
        {ATTR_DEVICE_CLASS: BinarySensorDeviceClass.WINDOW},
    )
    engine.evaluate()

    assert engine.assessment["ventilation_demand"] == VentilationDemand.URGENT
    assert engine.assessment["ventilation_activity"] == VentilationActivity.VENTILATING
    assert engine.assessment["window_recommendation"] == WindowRecommendation.NONE
    assert engine.assessment["context"] == (
        "Sofort weiterlüften: Die CO₂-Konzentration ist weiterhin sehr hoch."
    )


def test_hazardous_outdoor_air_stops_urgent_ventilation(
    hass: HomeAssistant,
) -> None:
    """Hazardous outdoor air stops an open window despite urgent indoor CO2."""
    hass.config.language = "de"
    interior = _area(hass, {CONF_ENVIRONMENT_WINDOWS: ["binary_sensor.window"]})
    _sensor(hass, interior, "sensor.co2", 2200, SensorDeviceClass.CO2, "ppm")
    _sensor(
        hass,
        interior,
        "sensor.indoor_pm25",
        20,
        SensorDeviceClass.PM25,
        UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
    )
    hass.states.async_set(
        "binary_sensor.window",
        STATE_OFF,
        {ATTR_DEVICE_CLASS: BinarySensorDeviceClass.WINDOW},
    )
    exterior = _area(hass, {CONF_TYPE: AREA_TYPE_EXTERIOR})
    _sensor(
        hass,
        exterior,
        "sensor.exterior_pm25",
        10,
        SensorDeviceClass.PM25,
        UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
    )
    hass.data.setdefault(MODULE_DATA, {})["exterior"] = {DATA_AREA_OBJECT: exterior}
    engine = AreaEnvironmentEngine(interior)
    indoor_state = engine.assessment["pollutant_state"]
    assert indoor_state == PollutantState.CRITICAL
    assert engine.assessment["dominant_indoor_pollutant"] == "co2"
    assert engine.assessment["air_exchange_suitability"] == (
        AirExchangeSuitability.FAVORABLE
    )
    assert engine.assessment["ventilation_strategy"] == VentilationStrategy.PASSIVE
    assert engine.assessment["air_cleaning_recommendation"] == (
        AirCleaningRecommendation.NOT_EFFECTIVE
    )
    assert engine.assessment["window_recommendation"] == WindowRecommendation.OPEN

    hass.states.async_set(
        "binary_sensor.window",
        STATE_ON,
        {ATTR_DEVICE_CLASS: BinarySensorDeviceClass.WINDOW},
    )
    engine.evaluate()
    assert engine.assessment["window_recommendation"] == WindowRecommendation.NONE

    hass.states.async_set(
        "sensor.exterior_pm25",
        "200",
        {
            ATTR_DEVICE_CLASS: SensorDeviceClass.PM25,
            ATTR_UNIT_OF_MEASUREMENT: UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
        },
    )
    engine.evaluate()

    assert engine.assessment["ventilation_demand"] == VentilationDemand.URGENT
    assert engine.assessment["pollutant_state"] == indoor_state
    assert engine.assessment["ventilation_strategy"] == (
        VentilationStrategy.FILTERED_MECHANICAL
    )
    assert engine.assessment["air_cleaning_recommendation"] == (
        AirCleaningRecommendation.NOT_EFFECTIVE
    )
    assert engine.assessment["ventilation_activity"] == VentilationActivity.VENTILATING
    assert engine.assessment["window_recommendation"] == WindowRecommendation.CLOSE
    assert "ventilation_should_stop" in engine.assessment["reason_codes"]
    assert "air_exchange_hazardous" in engine.assessment["reason_codes"]
    assert "outdoor_air_polluted" in engine.assessment["reason_codes"]
    assert "outdoor_air_polluted" not in engine.assessment["indoor_reason_codes"]
    assert "high_co2" not in engine.assessment["mitigation_reason_codes"]
    indoor_sources = engine.assessment["indoor_source_entities"]
    outdoor_sources = engine.assessment["outdoor_source_entities"]
    assert "outdoor_pm25" not in indoor_sources
    assert set(indoor_sources).isdisjoint(outdoor_sources)
    assert "outdoor_pm25" in outdoor_sources
    assert engine.assessment["context"] == (
        "Sofort weiterlüften: Die CO₂-Konzentration ist weiterhin sehr hoch. Lüften "
        "sofort beenden und Fenster schließen: Die Außenluft ist derzeit stark belastet."
    )


def test_hazardous_outdoor_air_closes_manually_opened_window(
    hass: HomeAssistant,
) -> None:
    """A safety close does not depend on an earlier window recommendation."""
    hass.config.language = "de"
    interior = _area(hass, {CONF_ENVIRONMENT_WINDOWS: ["binary_sensor.window"]})
    _sensor(
        hass,
        interior,
        "sensor.indoor_pm25",
        20,
        SensorDeviceClass.PM25,
        UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
    )
    hass.states.async_set(
        "binary_sensor.window",
        STATE_ON,
        {ATTR_DEVICE_CLASS: BinarySensorDeviceClass.WINDOW},
    )
    exterior = _area(hass, {CONF_TYPE: AREA_TYPE_EXTERIOR})
    _sensor(
        hass,
        exterior,
        "sensor.exterior_pm25",
        200,
        SensorDeviceClass.PM25,
        UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
    )
    hass.data.setdefault(MODULE_DATA, {})["exterior"] = {DATA_AREA_OBJECT: exterior}

    engine = AreaEnvironmentEngine(interior)
    assessment = engine.assessment

    assert engine._had_window_need is False
    assert assessment["window_recommendation"] == WindowRecommendation.CLOSE
    assert "ventilation_should_stop" in assessment["reason_codes"]
    assert "air_exchange_hazardous" in assessment["reason_codes"]
    assert assessment["context"] == (
        "Der aktuelle Messwert zeigt eine erhöhte Schadstoffbelastung: die "
        "Feinstaubbelastung PM2,5 ist erhöht. Die zeitbezogene Bewertung bleibt "
        "vorläufig, bis genügend Messhistorie vorliegt. Lüften sofort beenden und "
        "Fenster schließen: Die Außenluft ist derzeit stark belastet."
    )


def test_co2_requests_fan_and_window_when_both_are_configured(
    hass: HomeAssistant,
) -> None:
    """A configured fan and window both receive suitable ventilation advice."""
    area = _area(
        hass,
        {
            CONF_ENVIRONMENT_WINDOWS: ["binary_sensor.window"],
            CONF_ENVIRONMENT_VENTILATION_FANS: ["fan.ventilation"],
        },
    )
    _sensor(hass, area, "sensor.co2", 1500, SensorDeviceClass.CO2, "ppm")
    hass.states.async_set(
        "binary_sensor.window",
        STATE_OFF,
        {ATTR_DEVICE_CLASS: BinarySensorDeviceClass.WINDOW},
    )

    assessment = AreaEnvironmentEngine(area).assessment

    assert assessment["window_recommendation"] == WindowRecommendation.OPEN
    assert assessment["ventilation_fan_request"] == VentilationFanRequest.LOW


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


def test_primary_humidity_change_resets_history(hass: HomeAssistant, freezer) -> None:
    """Reloading with a new primary source cannot inherit old persistence."""
    area = _area(
        hass,
        {
            CONF_AREA_TEMPERATURE_SENSOR: "sensor.temperature",
            CONF_AREA_HUMIDITY_SENSOR: "sensor.humidity_a",
        },
    )
    _sensor(
        hass,
        area,
        "sensor.temperature",
        22,
        SensorDeviceClass.TEMPERATURE,
        UnitOfTemperature.CELSIUS,
    )
    _sensor(hass, area, "sensor.humidity_a", 72, SensorDeviceClass.HUMIDITY, "%")
    _sensor(hass, area, "sensor.humidity_b", 72, SensorDeviceClass.HUMIDITY, "%")
    old_engine = AreaEnvironmentEngine(area)
    freezer.tick(12 * 60 * 60)
    old_engine.evaluate()
    assert old_engine.assessment["mould_warning_duration_seconds"] == 12 * 60 * 60

    area.config[CONF_AREA_HUMIDITY_SENSOR] = "sensor.humidity_b"
    new_engine = AreaEnvironmentEngine(area)
    assert new_engine.assessment["mould_warning_duration_seconds"] == 0
    assert new_engine.assessment["humidity_warning_duration_seconds"] == 0


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
    _sensor(
        hass,
        area,
        "sensor.pm25",
        80,
        SensorDeviceClass.PM25,
        UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
    )
    hass.states.async_set(
        "binary_sensor.window",
        STATE_OFF,
        {ATTR_DEVICE_CLASS: BinarySensorDeviceClass.WINDOW},
    )
    area.entities["binary_sensor"] = [{ATTR_ENTITY_ID: "binary_sensor.window"}]
    engine = AreaEnvironmentEngine(area)
    assessment = engine.assessment

    assert assessment["air_quality"] == AirQualityState.GOOD
    assert assessment["pollutant_state"] == PollutantState.GOOD
    assert assessment["pollutant_assessments"]["pm25"]["quality"] == "limited"
    assert assessment["pollutant_assessments"]["pm25"]["current_state"] == (
        AirQualityState.CRITICAL
    )
    assert assessment["state"] == EnvironmentState.ATTENTION
    assert assessment["dominant_decision"] == "air_quality_provisional"
    assert "PM2.5" in assessment["context"]
    assert assessment["source_entities"]["pm25"]["entities"][0]["entity_id"] == (
        "sensor.pm25"
    )
    assert assessment["ventilation"] == VentilationState.NOT_REQUIRED
    assert assessment["ventilation_fan_request"] == VentilationFanRequest.NONE
    assert assessment["window_recommendation"] == WindowRecommendation.NONE

    freezer.tick(18 * 60 * 60)
    engine.evaluate()
    assert engine.assessment["air_quality"] == AirQualityState.CRITICAL
    assert engine.assessment["ventilation_fan_request"] == VentilationFanRequest.NONE
    assert engine.assessment["window_recommendation"] == WindowRecommendation.NONE
    assert "high_pm25" in engine.assessment["reason_codes"]


def test_no2_does_not_request_window_ventilation(hass: HomeAssistant, freezer) -> None:
    """Indoor NO2 affects air quality without claiming outdoor air is safer."""
    area = _area(hass)
    _sensor(
        hass,
        area,
        "sensor.no2",
        120,
        SensorDeviceClass.NITROGEN_DIOXIDE,
        UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
    )
    hass.states.async_set(
        "binary_sensor.window",
        STATE_OFF,
        {ATTR_DEVICE_CLASS: BinarySensorDeviceClass.WINDOW},
    )
    area.entities["binary_sensor"] = [{ATTR_ENTITY_ID: "binary_sensor.window"}]
    engine = AreaEnvironmentEngine(area)

    freezer.tick(18 * 60 * 60)
    engine.evaluate()

    assert engine.assessment["air_quality"] == AirQualityState.CRITICAL
    assert engine.assessment["ventilation"] == VentilationState.UNKNOWN
    assert engine.assessment["window_recommendation"] == WindowRecommendation.NONE
    assert engine.assessment["ventilation_fan_request"] == VentilationFanRequest.NONE


def test_pollutant_unit_must_match_matrix(hass: HomeAssistant) -> None:
    """A device class with incompatible units is ignored safely."""
    area = _area(hass)
    _sensor(hass, area, "sensor.pm25", 80, SensorDeviceClass.PM25, "ppm")
    assessment = AreaEnvironmentEngine(area).assessment

    assert assessment["air_quality"] == AirQualityState.UNKNOWN
    assert assessment["pollutant_state"] == PollutantState.UNKNOWN
    assert assessment["capabilities"]["pm25"] is False
    assert assessment["ignored_sources"]["sensor.pm25"] == {
        "reason": "unsupported_unit"
    }


def test_non_pollutant_area_sensors_are_not_candidates(hass: HomeAssistant) -> None:
    """Ordinary Area sensors never add unsupported-device-class diagnostics."""
    area = _area(hass)
    for entity_id, device_class in (
        ("sensor.kona_ev_battery_level", SensorDeviceClass.BATTERY),
        ("sensor.electricity_maps_power", SensorDeviceClass.POWER),
        ("sensor.pollenflug_index", SensorDeviceClass.ENUM),
    ):
        _sensor(hass, area, entity_id, 42, device_class)
    hass.states.async_set(
        "sensor.lidl_weststadt_offers",
        "13",
        {ATTR_FRIENDLY_NAME: "Example PM2.5"},
    )
    area.entities["sensor"].append({ATTR_ENTITY_ID: "sensor.lidl_weststadt_offers"})

    assessment = AreaEnvironmentEngine(area).assessment

    assert assessment["pollutants"] == {}
    assert assessment["ignored_sources"] == {}


def test_unavailable_typed_pollutant_is_diagnostic(hass: HomeAssistant) -> None:
    """An unavailable source is ignored only after official pollutant typing."""
    area = _area(hass)
    _sensor(
        hass,
        area,
        "sensor.pm25",
        STATE_UNAVAILABLE,
        SensorDeviceClass.PM25,
        UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
    )

    assessment = AreaEnvironmentEngine(area).assessment

    assert assessment["pollutants"] == {}
    assert assessment["ignored_sources"]["sensor.pm25"] == {"reason": "unavailable"}


def test_entity_name_does_not_override_device_class(hass: HomeAssistant) -> None:
    """A pollutant-looking entity ID cannot override official metadata."""
    entity_id = "sensor.example_wrong_class"
    area = _area(hass)
    hass.states.async_set(
        entity_id,
        "31.3",
        {
            ATTR_DEVICE_CLASS: SensorDeviceClass.HUMIDITY,
            ATTR_UNIT_OF_MEASUREMENT: UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
        },
    )
    area.entities["sensor"] = [{ATTR_ENTITY_ID: entity_id}]

    assessment = AreaEnvironmentEngine(area).assessment

    assert assessment["pollutants"] == {}
    assert assessment["pollutant_state"] == PollutantState.UNKNOWN
    assert assessment["ignored_sources"] == {}


def test_typed_pollutant_without_unit_is_ignored(hass: HomeAssistant) -> None:
    """A pollutant device class never causes a missing unit to be invented."""
    entity_id = "sensor.example_pm25"
    area = _area(hass)
    _sensor(hass, area, entity_id, 13, SensorDeviceClass.PM25)
    assessment = AreaEnvironmentEngine(area).assessment

    assert assessment["pollutants"] == {}
    assert assessment["pollutant_state"] == PollutantState.UNKNOWN
    assert assessment["ignored_sources"][entity_id] == {"reason": "unsupported_unit"}


@pytest.mark.parametrize("unit", ("µg/m³", "μg/m³"))
def test_microgram_unit_spellings_are_equivalent(
    hass: HomeAssistant, unit: str
) -> None:
    """Micro-sign and Greek-mu spellings normalize to the HA canonical unit."""
    area = _area(hass)
    _sensor(hass, area, "sensor.pm25", 13, SensorDeviceClass.PM25, unit)

    assessment = AreaEnvironmentEngine(area).assessment

    assert assessment["pollutants"] == {"pm25": 13.0}
    assert assessment["pollutant_state"] == PollutantState.UNKNOWN


def test_device_class_rejects_unsupported_ha_unit(hass: HomeAssistant) -> None:
    """A convertible unit is still rejected when HA disallows it for PM2.5."""
    area = _area(hass)
    _sensor(hass, area, "sensor.pm25", 0.02, SensorDeviceClass.PM25, "mg/m³")

    assessment = AreaEnvironmentEngine(area).assessment

    assert assessment["pollutants"] == {}
    assert assessment["pollutant_state"] == PollutantState.UNKNOWN
    assert assessment["ignored_sources"]["sensor.pm25"] == {
        "reason": "unsupported_unit"
    }


def test_supported_voc_mass_unit_is_converted(hass: HomeAssistant) -> None:
    """A Home Assistant-supported VOC mass unit converts internally."""
    area = _area(hass)
    _sensor(
        hass,
        area,
        "sensor.voc",
        1.0,
        SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS,
        UnitOfDensity.MILLIGRAMS_PER_CUBIC_METER,
    )

    assert AreaEnvironmentEngine(area).assessment["pollutants"] == {"voc": 1000.0}


@pytest.mark.parametrize(
    ("device_class", "unit", "expected"),
    (
        (SensorDeviceClass.CO, "ppm", 28.01 / 24.45),
        (SensorDeviceClass.NITROGEN_DIOXIDE, "ppb", 46.0055 / 24.45),
        (SensorDeviceClass.OZONE, "ppb", 47.9982 / 24.45),
    ),
)
def test_supported_gas_ratio_unit_is_converted(
    hass: HomeAssistant,
    device_class: SensorDeviceClass,
    unit: str,
    expected: float,
) -> None:
    """Supported gas ratios convert to each evaluation matrix's mass unit."""
    area = _area(hass)
    key = {
        SensorDeviceClass.CO: "co",
        SensorDeviceClass.NITROGEN_DIOXIDE: "no2",
        SensorDeviceClass.OZONE: "ozone",
    }[device_class]
    _sensor(hass, area, f"sensor.{key}", 1, device_class, unit)

    assert AreaEnvironmentEngine(area).assessment["pollutants"][key] == round(
        expected, 2
    )


@pytest.mark.parametrize(
    "entity_id", ("sensor.wendland_germany_pm25", "sensor.provider_xyz_4711")
)
def test_official_metadata_is_integration_name_independent(
    hass: HomeAssistant, entity_id: str
) -> None:
    """Official metadata is handled identically for arbitrary provider names."""
    area = _area(hass)
    _sensor(
        hass,
        area,
        entity_id,
        13,
        SensorDeviceClass.PM25,
        UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
    )

    assert AreaEnvironmentEngine(area).assessment["pollutants"] == {"pm25": 13.0}


@pytest.mark.parametrize(
    ("value", "expected_current"),
    (
        (10, AirQualityState.GOOD),
        (20, AirQualityState.DEGRADED),
        (50, AirQualityState.POOR),
        (80, AirQualityState.CRITICAL),
    ),
)
def test_time_based_pollutant_needs_history_for_final_state(
    hass: HomeAssistant, value: float, expected_current: AirQualityState
) -> None:
    """A current reading remains visible but is not a final rolling assessment."""
    area = _area(hass)
    _sensor(
        hass,
        area,
        "sensor.pm25",
        value,
        SensorDeviceClass.PM25,
        UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
    )

    assessment = AreaEnvironmentEngine(area).assessment

    assert assessment["pollutant_state"] == PollutantState.UNKNOWN
    assert assessment["air_quality"] == AirQualityState.UNKNOWN
    assert assessment["pollutant_assessments"]["pm25"]["current_state"] == (
        expected_current
    )


def test_pollutant_state_uses_worst_of_multiple_good_pollutants(
    hass: HomeAssistant,
) -> None:
    """Several valid unremarkable concentrations produce a good state."""
    area = _area(hass)
    for entity_id, value, device_class in (
        ("sensor.pm25", 9, SensorDeviceClass.PM25),
        ("sensor.pm10", 20, SensorDeviceClass.PM10),
        ("sensor.no2", 10, SensorDeviceClass.NITROGEN_DIOXIDE),
        ("sensor.ozone", 50, SensorDeviceClass.OZONE),
    ):
        _sensor(
            hass,
            area,
            entity_id,
            value,
            device_class,
            UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
        )

    assessment = AreaEnvironmentEngine(area).assessment

    assert assessment["pollutant_state"] == PollutantState.UNKNOWN
    assert assessment["dominant_indoor_pollutant"] == "unknown"
    assert set(assessment["pollutants"]) == {"pm25", "pm10", "no2", "ozone"}


@pytest.mark.parametrize(
    ("entity_id", "value", "device_class", "unit", "measurement"),
    (
        ("sensor.aqi", 200, SensorDeviceClass.AQI, None, {"aqi": 200.0}),
        (
            "sensor.pm1",
            7,
            SensorDeviceClass.PM1,
            "µg/m³",
            {"pm1": 7.0},
        ),
        (
            "sensor.voc_parts",
            5000,
            SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS_PARTS,
            "ppb",
            {"voc_parts": 5000.0},
        ),
    ),
)
def test_unclassified_scale_alone_has_unknown_pollutant_state(
    hass: HomeAssistant,
    entity_id: str,
    value: float,
    device_class: SensorDeviceClass,
    unit: str | None,
    measurement: dict[str, float],
) -> None:
    """AQI and VOC-parts remain measured but never set health severity."""
    area = _area(hass)
    _sensor(hass, area, entity_id, value, device_class, unit)

    assessment = AreaEnvironmentEngine(area).assessment

    assert assessment["pollutant_state"] == PollutantState.UNKNOWN
    assert assessment["pollutants"] == measurement


def test_aqi_does_not_override_valid_pm25_state(hass: HomeAssistant) -> None:
    """A valid concentration remains authoritative beside an unclassified AQI."""
    area = _area(hass)
    _sensor(hass, area, "sensor.aqi", 500, SensorDeviceClass.AQI)
    _sensor(
        hass,
        area,
        "sensor.pm25",
        10,
        SensorDeviceClass.PM25,
        UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
    )

    assert AreaEnvironmentEngine(area).assessment["pollutant_state"] == (
        PollutantState.UNKNOWN
    )


def test_voc_concentration_requires_supported_unit(
    hass: HomeAssistant,
) -> None:
    """Official VOC concentration metadata still requires a compatible unit."""
    valid_id = "sensor.voc"
    invalid_id = "sensor.voc_wrong_unit"
    area = _area(hass)
    _sensor(
        hass,
        area,
        valid_id,
        951,
        SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS,
        UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
    )
    _sensor(
        hass,
        area,
        invalid_id,
        5000,
        SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS,
        "ppb",
    )

    assessment = AreaEnvironmentEngine(area).assessment

    assert assessment["pollutants"]["voc"] == 951
    assert assessment["pollutant_state"] == PollutantState.ELEVATED
    assert assessment["source_entities"]["voc"]["mode"] == "direct"
    assert assessment["ignored_sources"][invalid_id] == {"reason": "unsupported_unit"}


def test_ignored_pollutant_does_not_worsen_valid_state(hass: HomeAssistant) -> None:
    """An invalid critical-looking value cannot affect the aggregate state."""
    area = _area(hass)
    _sensor(
        hass,
        area,
        "sensor.valid_pm25",
        10,
        SensorDeviceClass.PM25,
        UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
    )
    _sensor(
        hass,
        area,
        "sensor.invalid_pm25",
        999,
        SensorDeviceClass.PM25,
        "ppm",
    )

    assessment = AreaEnvironmentEngine(area).assessment

    assert assessment["pollutant_state"] == PollutantState.UNKNOWN
    assert assessment["pollutants"]["pm25"] == 10
    assert assessment["ignored_sources"]["sensor.invalid_pm25"] == {
        "reason": "unsupported_unit"
    }


def test_pollutant_exclusion_is_authoritative(hass: HomeAssistant) -> None:
    """General exclusions remove pollutant sources from every output."""
    area = _area(hass, {CONF_EXCLUDE_ENTITIES: ["sensor.pm25"]})
    _sensor(
        hass,
        area,
        "sensor.pm25",
        80,
        SensorDeviceClass.PM25,
        UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
    )

    assessment = AreaEnvironmentEngine(area).assessment

    assert assessment["capabilities"]["pm25"] is False
    assert "pm25" not in assessment["pollutants"]
    assert "pm25" not in assessment["pollutant_assessments"]
    assert "pm25" not in assessment["source_entities"]


async def test_pollutants_are_discovered_from_device_entity_and_include_areas(
    hass: HomeAssistant,
) -> None:
    """Discovery combines device, entity-Area, and loaded include sources."""
    area = _area(
        hass,
        {
            CONF_INCLUDE_ENTITIES: ["sensor.included_voc"],
        },
    )
    source_entry = MockConfigEntry(domain="test", data={})
    source_entry.add_to_hass(hass)
    device_registry = async_get_device_registry(hass)
    entity_registry = async_get_entity_registry(hass)
    device = device_registry.async_get_or_create(
        config_entry_id=source_entry.entry_id,
        identifiers={("test", "arbeitszimmer_klima")},
        name="Arbeitszimmer Klima",
    )
    device_registry.async_update_device(device.id, area_id=area.id)

    sources = (
        (
            "device_pm25",
            "arbeitszimmer_pm25",
            SensorDeviceClass.PM25,
            UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
            device.id,
            None,
        ),
        (
            "device_voc",
            "arbeitszimmer_voc",
            SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS,
            UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
            device.id,
            None,
        ),
        (
            "entity_pm25",
            "entity_area_pm25",
            SensorDeviceClass.PM25,
            UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
            None,
            area.id,
        ),
        (
            "included_voc",
            "included_voc",
            SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS,
            UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
            None,
            None,
        ),
    )
    for unique_id, object_id, device_class, unit, device_id, area_id in sources:
        registry_entry = entity_registry.async_get_or_create(
            "sensor",
            "test",
            unique_id,
            suggested_object_id=object_id,
            config_entry=source_entry,
            device_id=device_id,
            original_device_class=device_class,
            entity_category=(
                EntityCategory.DIAGNOSTIC if unique_id == "device_pm25" else None
            ),
            unit_of_measurement=unit,
        )
        if area_id:
            entity_registry.async_update_entity(
                registry_entry.entity_id, area_id=area_id
            )
        hass.states.async_set(
            registry_entry.entity_id,
            "20" if device_class == SensorDeviceClass.PM25 else "951",
            {
                ATTR_DEVICE_CLASS: device_class,
                ATTR_UNIT_OF_MEASUREMENT: unit,
                ATTR_FRIENDLY_NAME: object_id,
            },
        )
        if unique_id == "included_voc":
            area.entities.setdefault("sensor", []).append(
                {ATTR_ENTITY_ID: registry_entry.entity_id}
            )

    engine = AreaEnvironmentEngine(area)

    assert engine._sensor_ids[str(SensorDeviceClass.PM25)] == [
        "sensor.arbeitszimmer_pm25",
        "sensor.entity_area_pm25",
    ]
    assert engine._sensor_ids[str(SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS)] == [
        "sensor.arbeitszimmer_voc",
        "sensor.included_voc",
    ]
    assert len(engine.assessment["source_entities"]["pm25"]["entities"]) == 2
    assert len(engine.assessment["source_entities"]["voc"]["entities"]) == 2
    assert engine.assessment["pollutants"]["pm25"] == 20
    assert engine.assessment["pollutant_assessments"]["pm25"]["current"] == 20
    assert engine.assessment["pollutant_assessments"]["pm25"]["quality"] == "limited"

    engine.unload()


async def test_multiple_loaded_include_pollutants_are_discovered_together(
    hass: HomeAssistant,
) -> None:
    """All valid loaded include_entities remain pollutant candidates."""
    included = {
        "sensor.included_pm25": (SensorDeviceClass.PM25, 9),
        "sensor.included_pm10": (SensorDeviceClass.PM10, 20),
        "sensor.included_no2": (SensorDeviceClass.NITROGEN_DIOXIDE, 10),
        "sensor.included_ozone": (SensorDeviceClass.OZONE, 50),
    }
    area = _area(hass, {CONF_INCLUDE_ENTITIES: list(included)})
    source_entry = MockConfigEntry(domain="test", data={})
    source_entry.add_to_hass(hass)
    entity_registry = async_get_entity_registry(hass)

    for entity_id, (device_class, value) in included.items():
        entry = entity_registry.async_get_or_create(
            "sensor",
            "test",
            entity_id,
            suggested_object_id=entity_id.removeprefix("sensor."),
            config_entry=source_entry,
            original_device_class=device_class,
            unit_of_measurement=UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
        )
        hass.states.async_set(
            entry.entity_id,
            str(value),
            {
                ATTR_DEVICE_CLASS: device_class,
                ATTR_UNIT_OF_MEASUREMENT: UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
            },
        )
        area.entities.setdefault("sensor", []).append({ATTR_ENTITY_ID: entry.entity_id})

    assessment = AreaEnvironmentEngine(area).assessment

    assert assessment["pollutants"] == {
        "pm25": 9.0,
        "pm10": 20.0,
        "no2": 10.0,
        "ozone": 50.0,
    }
    assert assessment["pollutant_state"] == PollutantState.UNKNOWN
    assert all(
        assessment["capabilities"][capability]
        for capability in ("pm25", "pm10", "no2", "ozone", "air_quality")
    )


async def test_registry_pollutants_recover_when_states_arrive_late(
    hass: HomeAssistant,
) -> None:
    """Registry device classes keep late PM states tracked after startup."""
    area = _area(hass)
    source_entry = MockConfigEntry(domain="test", data={})
    source_entry.add_to_hass(hass)
    entity_registry = async_get_entity_registry(hass)

    for device_class in (SensorDeviceClass.PM25, SensorDeviceClass.PM10):
        registry_entry = entity_registry.async_get_or_create(
            "sensor",
            "test",
            str(device_class),
            suggested_object_id=str(device_class),
            config_entry=source_entry,
            original_device_class=device_class,
            unit_of_measurement=UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
        )
        entity_registry.async_update_entity(registry_entry.entity_id, area_id=area.id)

    engine = AreaEnvironmentEngine(area)

    assert engine._sensor_ids[str(SensorDeviceClass.PM25)] == ["sensor.pm25"]
    assert engine._sensor_ids[str(SensorDeviceClass.PM10)] == ["sensor.pm10"]
    assert engine.assessment["pollutants"] == {}

    hass.states.async_set(
        "sensor.pm25",
        "20",
        {
            ATTR_DEVICE_CLASS: SensorDeviceClass.PM25,
            ATTR_UNIT_OF_MEASUREMENT: UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
        },
    )
    hass.states.async_set(
        "sensor.pm10",
        "50",
        {
            ATTR_DEVICE_CLASS: SensorDeviceClass.PM10,
            ATTR_UNIT_OF_MEASUREMENT: UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
        },
    )
    await hass.async_block_till_done()

    assert engine.assessment["pollutants"] == {"pm25": 20.0, "pm10": 50.0}
    assert set(engine.assessment["pollutant_assessments"]) == {"pm25", "pm10"}
    assert engine.assessment["capabilities"]["pm25"] is True
    assert engine.assessment["capabilities"]["pm10"] is True

    engine.unload()


def test_unclassified_pollutants_are_not_repaired(hass: HomeAssistant) -> None:
    """Names and units cannot replace valid Home Assistant device classes."""
    pm25_id = "sensor.vendor_pm25"
    misclassified_pm25_id = "sensor.vendor_misclassified_pm25"
    ozone_id = "sensor.vendor_ozone"
    attributes = {
        ATTR_FRIENDLY_NAME: "PM2.5",
        ATTR_UNIT_OF_MEASUREMENT: UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
    }
    hass.states.async_set(pm25_id, "13", attributes)
    hass.states.async_set(
        misclassified_pm25_id,
        "13",
        {
            ATTR_DEVICE_CLASS: SensorDeviceClass.HUMIDITY,
            ATTR_UNIT_OF_MEASUREMENT: UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
        },
    )
    hass.states.async_set(ozone_id, "19.1", {ATTR_FRIENDLY_NAME: "Ozone"})

    area = _area(hass)
    area.entities["sensor"] = [
        {ATTR_ENTITY_ID: pm25_id},
        {ATTR_ENTITY_ID: misclassified_pm25_id},
        {ATTR_ENTITY_ID: ozone_id},
    ]
    engine = AreaEnvironmentEngine(area)

    assert engine._sensor_ids[str(SensorDeviceClass.PM25)] == []
    assert engine.assessment["pollutants"] == {}
    assert engine.assessment["ignored_sources"] == {}

    engine.unload()


def test_explicit_primary_sources_override_device_class(hass: HomeAssistant) -> None:
    """Manual temperature and humidity roles outrank incorrect metadata."""
    area = _area(
        hass,
        {
            CONF_AREA_TEMPERATURE_SENSOR: "sensor.manual_temperature",
            CONF_AREA_HUMIDITY_SENSOR: "sensor.manual_humidity",
        },
    )
    hass.states.async_set(
        "sensor.manual_temperature",
        "21.5",
        {
            ATTR_DEVICE_CLASS: SensorDeviceClass.PRESSURE,
            ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS,
        },
    )
    hass.states.async_set("sensor.manual_humidity", "48")

    assessment = AreaEnvironmentEngine(area).assessment

    assert assessment["temperature"] == 21.5
    assert assessment["relative_humidity"] == 48
    assert assessment["source_entities"]["temperature"]["mode"] == "primary"
    assert assessment["source_entities"]["humidity"]["mode"] == "primary"


def test_pm_uses_observed_rolling_day(hass: HomeAssistant, freezer) -> None:
    """PM uses elapsed-time weighting, coverage quality, and a 24-hour window."""
    area = _area(hass)
    _sensor(
        hass,
        area,
        "sensor.pm25",
        10,
        SensorDeviceClass.PM25,
        UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
    )
    engine = AreaEnvironmentEngine(area)
    assert engine.assessment["air_quality"] == AirQualityState.UNKNOWN
    pm25 = engine.assessment["pollutant_assessments"]["pm25"]
    assert pm25["current"] == 10.0
    assert pm25["current_state"] == AirQualityState.GOOD
    assert pm25["rolling_24h"] is None
    assert pm25["coverage_hours"] == 0.0
    assert pm25["assessment_quality"] == "limited"
    assert pm25["guideline_value"] == 15
    assert pm25["guideline_period"] == "24h"
    assert pm25["guideline_exceeded"] is False
    assert pm25["severity"] == AirQualityState.UNKNOWN
    assert pm25["provisional_alert"] is False
    assert pm25["severity_basis"] == "insufficient_history"

    freezer.tick(6 * 60 * 60)

    hass.states.async_set(
        "sensor.pm25",
        "80",
        {
            ATTR_DEVICE_CLASS: SensorDeviceClass.PM25,
            ATTR_UNIT_OF_MEASUREMENT: UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
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


def test_limited_rolling_exceedance_does_not_set_severity(
    hass: HomeAssistant, freezer
) -> None:
    """An elevated partial mean cannot become a final 24-hour assessment."""
    area = _area(hass)
    _sensor(
        hass,
        area,
        "sensor.pm25",
        17,
        SensorDeviceClass.PM25,
        UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
    )
    engine = AreaEnvironmentEngine(area)
    freezer.tick(3 * 60 * 60)
    hass.states.async_set(
        "sensor.pm25",
        "8",
        {
            ATTR_DEVICE_CLASS: SensorDeviceClass.PM25,
            ATTR_UNIT_OF_MEASUREMENT: UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
        },
    )
    engine.evaluate()

    pm25 = engine.assessment["pollutant_assessments"]["pm25"]
    assert pm25["current_state"] == AirQualityState.GOOD
    assert pm25["rolling_24h"] == 17
    assert pm25["coverage_hours"] == 3
    assert pm25["assessment_quality"] == "limited"
    assert pm25["severity"] == AirQualityState.UNKNOWN
    assert pm25["provisional_alert"] is False
    assert engine.assessment["pollutant_state"] == PollutantState.UNKNOWN
    assert engine.assessment["air_quality"] == AirQualityState.UNKNOWN


def test_elevated_current_value_is_only_a_provisional_alert(
    hass: HomeAssistant, freezer
) -> None:
    """An elevated current value warns without replacing the 24-hour result."""
    area = _area(hass)
    _sensor(
        hass,
        area,
        "sensor.pm25",
        24,
        SensorDeviceClass.PM25,
        UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
    )
    engine = AreaEnvironmentEngine(area)
    freezer.tick(3 * 60 * 60)
    engine.evaluate()

    pm25 = engine.assessment["pollutant_assessments"]["pm25"]
    assert pm25["current_state"] == AirQualityState.DEGRADED
    assert pm25["assessment_quality"] == "limited"
    assert pm25["severity"] == AirQualityState.UNKNOWN
    assert pm25["provisional_alert"] is True
    assert "high_pm25_current" in engine.assessment["reason_codes"]
    assert engine.assessment["pollutant_state"] == PollutantState.UNKNOWN
    assert engine.assessment["air_quality"] == AirQualityState.UNKNOWN


@pytest.mark.parametrize(
    ("value", "expected_severity", "expected_state"),
    (
        (12, AirQualityState.GOOD, PollutantState.GOOD),
        (22, AirQualityState.DEGRADED, PollutantState.ELEVATED),
    ),
)
def test_sufficient_rolling_history_sets_final_state(
    hass: HomeAssistant,
    freezer,
    value: float,
    expected_severity: AirQualityState,
    expected_state: PollutantState,
) -> None:
    """A covered 24-hour assessment contributes its rolling severity."""
    area = _area(hass)
    _sensor(
        hass,
        area,
        "sensor.pm25",
        value,
        SensorDeviceClass.PM25,
        UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
    )
    engine = AreaEnvironmentEngine(area)
    freezer.tick(20 * 60 * 60)
    engine.evaluate()

    pm25 = engine.assessment["pollutant_assessments"]["pm25"]
    assert pm25["rolling_24h"] == value
    assert pm25["coverage_hours"] == 20
    assert pm25["assessment_quality"] == "sufficient"
    assert pm25["severity"] == expected_severity
    assert pm25["provisional_alert"] is False
    assert engine.assessment["pollutant_state"] == expected_state


def test_worst_covered_pollutant_is_dominant(hass: HomeAssistant, freezer) -> None:
    """The worst of several covered rolling assessments is deterministic."""
    area = _area(hass)
    for entity_id, value, device_class in (
        ("sensor.pm25", 9, SensorDeviceClass.PM25),
        ("sensor.pm10", 20, SensorDeviceClass.PM10),
        ("sensor.no2", 30, SensorDeviceClass.NITROGEN_DIOXIDE),
        ("sensor.ozone", 50, SensorDeviceClass.OZONE),
    ):
        _sensor(
            hass,
            area,
            entity_id,
            value,
            device_class,
            UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
        )
    engine = AreaEnvironmentEngine(area)
    freezer.tick(20 * 60 * 60)
    engine.evaluate()

    assert engine.assessment["pollutant_state"] == PollutantState.ELEVATED
    assert engine.assessment["dominant_indoor_pollutant"] == "no2"


def test_higher_pollutant_bands_are_operational_metadata(
    hass: HomeAssistant,
) -> None:
    """Higher bands are not represented as additional scientific guidelines."""
    area = _area(hass)
    _sensor(
        hass,
        area,
        "sensor.co",
        5,
        SensorDeviceClass.CO,
        UnitOfDensity.MILLIGRAMS_PER_CUBIC_METER,
    )
    assessment = AreaEnvironmentEngine(area).assessment["pollutant_assessments"]["co"]

    assert assessment["guideline_value"] == 4
    assert assessment["guideline_period"] == "24h"
    assert assessment["operational_thresholds"] == {
        "poor": 7,
        "critical": 10,
        "period": "24h",
        "basis": "adaptive_areas_operational",
    }


def test_no2_short_term_state_requires_coverage(hass: HomeAssistant, freezer) -> None:
    """The one-hour NO2 result contributes only after 45 minutes of coverage."""
    area = _area(hass)
    _sensor(
        hass,
        area,
        "sensor.no2",
        120,
        SensorDeviceClass.NITROGEN_DIOXIDE,
        UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
    )
    engine = AreaEnvironmentEngine(area)
    freezer.tick(18 * 60)
    engine.evaluate()

    no2 = engine.assessment["pollutant_assessments"]["no2"]
    assert no2["short_term_coverage_hours"] == 0.3
    assert no2["short_term_quality"] == "limited"
    assert no2["short_term_state"] == AirQualityState.UNKNOWN
    assert engine.assessment["pollutant_state"] == PollutantState.UNKNOWN

    freezer.tick(36 * 60)
    engine.evaluate()

    no2 = engine.assessment["pollutant_assessments"]["no2"]
    assert no2["short_term_coverage_hours"] == 0.9
    assert no2["short_term_quality"] == "sufficient"
    assert no2["short_term_state"] == AirQualityState.DEGRADED
    assert engine.assessment["pollutant_state"] == PollutantState.ELEVATED


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
    assert assessment["comfort_confidence"] == "not_applicable"
    assert assessment["cooling"] == CoolingState.NOT_REQUIRED


def test_outdoor_moisture_can_keep_window_closed(hass: HomeAssistant) -> None:
    """Humidity advice compares moisture ratio instead of relative humidity alone."""
    hass.config.language = "de"
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
    assert "window_should_remain_closed" in assessment["reason_codes"]
    assert assessment["ventilation_fan_request"] == VentilationFanRequest.NONE
    assert assessment["context"] == (
        "Die Luftfeuchtigkeit ist sehr hoch. Luftaustausch ist erforderlich. Nicht "
        "lüften: Die Außenluft ist derzeit feuchter und würde den Feuchteabbau nicht "
        "unterstützen."
    )


def test_outdoor_moisture_stops_manually_opened_window(
    hass: HomeAssistant,
) -> None:
    """Unfavorable moisture closes an open window without prior engine advice."""
    hass.config.language = "de"
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
        STATE_ON,
        {ATTR_DEVICE_CLASS: BinarySensorDeviceClass.WINDOW},
    )

    engine = AreaEnvironmentEngine(area)
    assessment = engine.assessment

    assert engine._had_window_need is False
    assert assessment["ventilation_activity"] == VentilationActivity.VENTILATING
    assert assessment["moisture_ventilation"] == "unfavorable"
    assert assessment["window_recommendation"] == WindowRecommendation.CLOSE
    assert "ventilation_should_stop" in assessment["reason_codes"]
    assert "outdoor_air_more_humid" in assessment["reason_codes"]
    assert assessment["context"] == (
        "Weiter lüften: Die Luftfeuchtigkeit ist sehr hoch. Lüften beenden und Fenster "
        "schließen: Die Außenluft ist für den Feuchteabbau derzeit ungünstig."
    )


def test_exclusion_is_authoritative_and_sources_are_transparent(
    hass: HomeAssistant,
) -> None:
    """Explicit climate assignments override exclusions and expose their source."""
    area = _area(
        hass,
        {
            CONF_AREA_TEMPERATURE_SENSOR: "sensor.bad_temperature",
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

    assert assessment["temperature"] == 40
    assert assessment["outdoor_temperature"] is None
    assert assessment["source_entities"]["temperature"] == {
        "mode": "primary",
        "configured": True,
        "available": True,
        "entity_id": "sensor.bad_temperature",
        "name": "bad temperature",
    }
    assert "primary_temperature_sensor_unavailable" not in assessment["reason_codes"]


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
    assert engine.assessment["cooling"] == CoolingState.ACTIVE_RECOMMENDED
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
        UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
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
    assert assessment["pollutant_assessments"]["voc"]["basis_type"] == (
        "precaution_indicator"
    )
    assert assessment["pollutant_assessments"]["voc_parts"]["quality"] == (
        "unsupported_scale"
    )


async def test_room_usage_uses_presence_transitions_only(
    hass: HomeAssistant, freezer
) -> None:
    """Cleaning Tracker accumulates from existing presence transitions."""
    area = _area(
        hass,
        {
            CONF_ENABLED_FEATURES: {
                CONF_FEATURE_ROOM_USAGE: {CONF_PRESENCE_MINUTES_TO_DUE: 120}
            }
        },
        environment=False,
    )
    engine = await RoomUsageEngine.async_create(area)
    assert engine.assessment["score"] == 0

    area.states = ["occupied"]
    engine._area_state_changed(area.id, None)
    assert len(area.decision_trace.export()) == 1
    freezer.tick(2 * 60 * 60)
    await engine._async_periodic_update(dt_util.utcnow())
    assert engine.assessment["score"] == 100
    assert engine.assessment["due"] is True

    area.states = ["clear"]
    engine._area_state_changed(area.id, None)
    assert len(area.decision_trace.export()) == 2
    await engine.async_unload()


def test_health_warning_has_highest_context_priority(hass: HomeAssistant) -> None:
    """An existing Area Health warning outranks environmental advice."""
    area = _area(hass)
    area.config[CONF_ENABLED_FEATURES][CONF_FEATURE_HEALTH] = {}
    hass.states.async_set("binary_sensor.adaptive_areas_health_kitchen", STATE_ON)
    _sensor(hass, area, "sensor.co2", 2200, SensorDeviceClass.CO2, "ppm")
    assessment = AreaEnvironmentEngine(area).assessment

    assert assessment["health_alert"] is True
    assert assessment["dominant_decision"] == "health_alert"
    assert "health_alert" in assessment["indoor_reason_codes"]
    assert "health_alert" not in assessment["mitigation_reason_codes"]


def test_german_context_is_human_readable(hass: HomeAssistant) -> None:
    """Context renders localized prose while reasons remain stable."""
    hass.config.language = "de"
    area = _area(hass)
    _sensor(hass, area, "sensor.co2", 1500, SensorDeviceClass.CO2, "ppm")
    assessment = AreaEnvironmentEngine(area).assessment

    assert assessment["context"].startswith("Die CO₂-Konzentration")
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


def test_humidity_changes_combined_comfort(hass: HomeAssistant) -> None:
    """Combined comfort exposes humidity discomfort separately from temperature."""
    area = _area(hass)
    _sensor(
        hass,
        area,
        "sensor.room_temperature",
        22,
        SensorDeviceClass.TEMPERATURE,
        UnitOfTemperature.CELSIUS,
    )
    _sensor(hass, area, "sensor.room_humidity", 70, SensorDeviceClass.HUMIDITY, "%")

    assessment = AreaEnvironmentEngine(area).assessment

    assert assessment["temperature_state"] == ComfortState.COMFORTABLE
    assert assessment["humidity_comfort_state"] == HumidityState.HIGH
    assert assessment["combined_comfort"] == CombinedComfortState.HUMIDITY_TOO_HIGH


def test_polluted_exterior_air_blocks_window_exchange(hass: HomeAssistant) -> None:
    """Conservative exterior pollution maximum blocks window ventilation."""
    hass.config.language = "de"
    interior = _area(hass, {CONF_ENVIRONMENT_WINDOWS: ["binary_sensor.window"]})
    _sensor(hass, interior, "sensor.co2", 1500, SensorDeviceClass.CO2, "ppm")
    _sensor(
        hass,
        interior,
        "sensor.indoor_pm25",
        20,
        SensorDeviceClass.PM25,
        UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
    )
    hass.states.async_set(
        "binary_sensor.window",
        STATE_OFF,
        {ATTR_DEVICE_CLASS: BinarySensorDeviceClass.WINDOW},
    )
    exterior = _area(hass, {CONF_TYPE: AREA_TYPE_EXTERIOR})
    _sensor(
        hass,
        exterior,
        "sensor.exterior_pm25",
        200,
        SensorDeviceClass.PM25,
        UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
    )
    hass.data.setdefault(MODULE_DATA, {})["exterior"] = {DATA_AREA_OBJECT: exterior}

    engine = AreaEnvironmentEngine(interior)
    assessment = engine.assessment

    assert assessment["air_exchange_suitability"] == AirExchangeSuitability.HAZARDOUS
    assert assessment["window_recommendation"] == WindowRecommendation.KEEP_CLOSED
    assert "window_should_remain_closed" in assessment["reason_codes"]
    assert "outdoor_air_polluted" in assessment["reason_codes"]
    assert assessment["source_entities"]["outdoor_pm25"]["mode"] == (
        "exterior_air_quality"
    )
    assert assessment["context"] == (
        "Die CO₂-Konzentration ist erhöht. Luftaustausch wird empfohlen. Fenster "
        "geschlossen halten: Die Außenluft ist derzeit stark belastet."
    )


def test_more_polluted_outdoor_air_keeps_window_closed(hass: HomeAssistant) -> None:
    """Unfavorable outdoor pollution blocks a generic ventilation prompt."""
    hass.config.language = "de"
    interior = _area(hass, {CONF_ENVIRONMENT_WINDOWS: ["binary_sensor.window"]})
    _sensor(hass, interior, "sensor.co2", 1500, SensorDeviceClass.CO2, "ppm")
    _sensor(
        hass,
        interior,
        "sensor.indoor_pm25",
        20,
        SensorDeviceClass.PM25,
        UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
    )
    hass.states.async_set(
        "binary_sensor.window",
        STATE_OFF,
        {ATTR_DEVICE_CLASS: BinarySensorDeviceClass.WINDOW},
    )
    exterior = _area(hass, {CONF_TYPE: AREA_TYPE_EXTERIOR})
    _sensor(
        hass,
        exterior,
        "sensor.exterior_pm25",
        25,
        SensorDeviceClass.PM25,
        UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
    )
    hass.data.setdefault(MODULE_DATA, {})["exterior"] = {DATA_AREA_OBJECT: exterior}

    engine = AreaEnvironmentEngine(interior)
    assessment = engine.assessment

    assert assessment["air_exchange_suitability"] == AirExchangeSuitability.UNFAVORABLE
    assert assessment["window_recommendation"] == WindowRecommendation.KEEP_CLOSED
    assert "window_should_remain_closed" in assessment["reason_codes"]
    assert assessment["context"] == (
        "Die CO₂-Konzentration ist erhöht. Luftaustausch wird empfohlen. Fenster "
        "geschlossen halten: Die Außenluft ist derzeit stärker belastet als die "
        "Innenluft."
    )

    hass.states.async_set(
        "binary_sensor.window",
        STATE_ON,
        {ATTR_DEVICE_CLASS: BinarySensorDeviceClass.WINDOW},
    )
    engine.evaluate()

    assert engine.assessment["window_recommendation"] == WindowRecommendation.CLOSE
    assert "ventilation_should_stop" in engine.assessment["reason_codes"]
    assert engine.assessment["context"] == (
        "Weiter lüften: Die CO₂-Konzentration ist erhöht. Lüften beenden und Fenster "
        "schließen: Die Außenluft ist inzwischen stärker belastet als die Innenluft."
    )


def test_particle_mitigation_changes_without_changing_indoor_state(
    hass: HomeAssistant,
) -> None:
    """Outdoor comparison stays separate from limited indoor severity."""
    interior = _area(hass, {CONF_ENVIRONMENT_WINDOWS: ["binary_sensor.window"]})
    _sensor(
        hass,
        interior,
        "sensor.indoor_pm25",
        80,
        SensorDeviceClass.PM25,
        UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
    )
    hass.states.async_set(
        "binary_sensor.window",
        STATE_OFF,
        {ATTR_DEVICE_CLASS: BinarySensorDeviceClass.WINDOW},
    )
    exterior = _area(hass, {CONF_TYPE: AREA_TYPE_EXTERIOR})
    _sensor(
        hass,
        exterior,
        "sensor.outdoor_pm25",
        5,
        SensorDeviceClass.PM25,
        UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
    )
    hass.data.setdefault(MODULE_DATA, {})["exterior"] = {DATA_AREA_OBJECT: exterior}
    engine = AreaEnvironmentEngine(interior)

    indoor_state = engine.assessment["pollutant_state"]
    assert indoor_state == PollutantState.UNKNOWN
    assert engine.assessment["dominant_indoor_pollutant"] == "unknown"
    assert engine.assessment["ventilation_demand"] == VentilationDemand.UNKNOWN
    assert engine.assessment["ventilation_strategy"] == VentilationStrategy.UNKNOWN
    assert engine.assessment["window_recommendation"] == WindowRecommendation.NONE
    assert engine.assessment["air_cleaning_recommendation"] == (
        AirCleaningRecommendation.NONE
    )

    hass.states.async_set(
        "sensor.outdoor_pm25",
        "200",
        {
            ATTR_DEVICE_CLASS: SensorDeviceClass.PM25,
            ATTR_UNIT_OF_MEASUREMENT: UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
        },
    )
    engine.evaluate()

    assert engine.assessment["pollutant_state"] == indoor_state
    assert engine.assessment["indoor_pollutant_measurements"] == {"pm25": 80.0}
    assert engine.assessment["air_exchange_suitability"] == (
        AirExchangeSuitability.HAZARDOUS
    )
    assert engine.assessment["ventilation_strategy"] == VentilationStrategy.UNKNOWN
    assert engine.assessment["window_recommendation"] == (
        WindowRecommendation.KEEP_CLOSED
    )
    assert engine.assessment["air_cleaning_recommendation"] == (
        AirCleaningRecommendation.NONE
    )
    assert "outdoor_air_polluted" not in engine.assessment["indoor_reason_codes"]
    assert not any(
        reason.startswith("high_pm25")
        for reason in engine.assessment["mitigation_reason_codes"]
    )


def test_exterior_assessment_omits_indoor_actions(hass: HomeAssistant) -> None:
    """Exterior Area Climate publishes measurements without indoor advice."""
    exterior = _area(hass, {CONF_TYPE: AREA_TYPE_EXTERIOR})
    _sensor(
        hass,
        exterior,
        "sensor.garden_temperature",
        18,
        SensorDeviceClass.TEMPERATURE,
        UnitOfTemperature.CELSIUS,
    )
    _sensor(
        hass,
        exterior,
        "sensor.garden_humidity",
        55,
        SensorDeviceClass.HUMIDITY,
        "%",
    )

    assessment = AreaEnvironmentEngine(exterior).assessment

    assert assessment["temperature"] == 18
    assert assessment["relative_humidity"] == 55
    for absent in (
        "comfort",
        "combined_comfort",
        "ventilation",
        "ventilation_state",
        "ventilation_demand",
        "ventilation_activity",
        "cooling",
        "air_exchange_suitability",
        "window_recommendation",
        "ventilation_fan_request",
        "circulation_fan_request",
    ):
        assert absent not in assessment


def test_no2_one_hour_precaution_assessment(hass: HomeAssistant, freezer) -> None:
    """NO2 combines 24-hour guidance with one-hour indoor precaution values."""
    area = _area(hass)
    _sensor(
        hass,
        area,
        "sensor.no2",
        100,
        SensorDeviceClass.NITROGEN_DIOXIDE,
        UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
    )
    engine = AreaEnvironmentEngine(area)
    freezer.tick(60 * 60)
    engine.evaluate()

    no2 = engine.assessment["pollutant_assessments"]["no2"]
    assert no2["rolling_1h"] == 100
    assert no2["short_term_quality"] == "sufficient"
    assert no2["short_term_state"] == AirQualityState.DEGRADED
    assert "no2_short_term_elevated" in engine.assessment["reason_codes"]


async def test_room_usage_is_independent_optional_feature(
    hass: HomeAssistant,
) -> None:
    """Room Usage creates dedicated runtime without Room Climate."""
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    data[CONF_ENABLED_FEATURES] = {CONF_FEATURE_ROOM_USAGE: {}}
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    await init_integration(hass, [entry])

    area = hass.data[MODULE_DATA][entry.entry_id][DATA_AREA_OBJECT]
    assert area.environment is None
    assert area.room_usage is not None
    state = hass.states.get(f"sensor.adaptive_areas_room_usage_{DEFAULT_MOCK_AREA}")
    assert state is not None
    assert state.state == "0.0"
    assert state.attributes["cumulative_presence_seconds"] == 0
    assert state.attributes["presence_minutes_to_due"] == (
        DEFAULT_PRESENCE_MINUTES_TO_DUE
    )
    due = hass.states.get(
        f"binary_sensor.adaptive_areas_room_usage_{DEFAULT_MOCK_AREA}_cleaning_due"
    )
    assert due is not None
    assert due.state == STATE_OFF

    await shutdown_integration(hass, [entry])


async def test_room_usage_enable_disable_reload(hass: HomeAssistant) -> None:
    """Room Usage runtime and dedicated entity follow feature selection."""
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    entry = MockConfigEntry(domain=DOMAIN, data=data, version=2, minor_version=6)
    await init_integration(hass, [entry])
    entity_id = f"sensor.adaptive_areas_room_usage_{DEFAULT_MOCK_AREA}"
    assert hass.states.get(entity_id) is None

    hass.config_entries.async_update_entry(
        entry,
        options={**data, CONF_ENABLED_FEATURES: {CONF_FEATURE_ROOM_USAGE: {}}},
    )
    await hass.async_block_till_done()
    area = hass.data[MODULE_DATA][entry.entry_id][DATA_AREA_OBJECT]
    assert area.room_usage is not None
    assert hass.states.get(entity_id) is not None

    hass.config_entries.async_update_entry(
        entry, options={**data, CONF_ENABLED_FEATURES: {}}
    )
    await hass.async_block_till_done()
    area = hass.data[MODULE_DATA][entry.entry_id][DATA_AREA_OBJECT]
    assert area.room_usage is None
    assert hass.states.get(entity_id) is None

    await shutdown_integration(hass, [entry])


async def test_room_climate_is_disabled_by_default(
    hass: HomeAssistant,
) -> None:
    """Regular indoor Areas do no hidden evaluation work by default."""
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


async def test_enabled_room_climate_publishes_pollutant_context(
    hass: HomeAssistant,
) -> None:
    """Real setup path overlays options and publishes a capability-aware state."""
    temperature = MockSensor(
        name="primary_temperature",
        unique_id="primary_temperature_runtime",
        native_value=21.5,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        unit_of_measurement=UnitOfTemperature.CELSIUS,
    )
    humidity = MockSensor(
        name="primary_humidity",
        unique_id="primary_humidity_runtime",
        native_value=50,
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement="%",
        unit_of_measurement="%",
    )
    pm25 = MockSensor(
        name="pm25",
        unique_id="pm25_runtime",
        native_value=80,
        device_class=SensorDeviceClass.PM25,
        native_unit_of_measurement=UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
        unit_of_measurement=UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
    )
    await setup_mock_entities(
        hass, "sensor", {DEFAULT_MOCK_AREA: [temperature, humidity, pm25]}
    )
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=data,
        options={
            **data,
            CONF_ENABLED_FEATURES: {CONF_FEATURE_ENVIRONMENT: {}},
            CONF_AREA_TEMPERATURE_SENSOR: temperature.entity_id,
            CONF_AREA_HUMIDITY_SENSOR: humidity.entity_id,
            CONF_ROOM_CATEGORY: RoomCategory.LIVING_SEDENTARY,
        },
        version=2,
        minor_version=5,
    )
    await init_integration(hass, [entry])

    area = hass.data[MODULE_DATA][entry.entry_id][DATA_AREA_OBJECT]
    assert area.config[CONF_AREA_TEMPERATURE_SENSOR] == temperature.entity_id
    assert area.config[CONF_AREA_HUMIDITY_SENSOR] == humidity.entity_id
    assert area.environment is not None
    state = hass.states.get(f"sensor.adaptive_areas_environment_{DEFAULT_MOCK_AREA}")
    assert state is not None
    assert state.state == EnvironmentState.ATTENTION
    assert "humidex" not in state.attributes
    assert state.attributes["comfort"] != ComfortState.UNKNOWN
    assert state.attributes["humidity"] != HumidityState.UNKNOWN
    assert state.attributes["pollutant_state"] == PollutantState.UNKNOWN
    assert state.attributes["dominant_indoor_pollutant"] == "unknown"
    assert state.attributes["indoor_source_entities"] == sorted(
        [temperature.entity_id, humidity.entity_id, pm25.entity_id]
    )
    assert state.attributes["outdoor_source_entities"] == []
    assert state.attributes["source_entities"] == sorted(
        [temperature.entity_id, humidity.entity_id, pm25.entity_id]
    )
    assert state.attributes["indoor_pollutant_measurements"]["pm25"] == 80
    assert state.attributes["pollutant_measurements"]["pm25"] == 80
    assert (
        state.attributes["indoor_pollutant_assessments"]["pm25"]["current_state"]
        == AirQualityState.CRITICAL
    )
    assert state.attributes["pollutant_assessments"]["pm25"]["current_state"] == (
        AirQualityState.CRITICAL
    )
    assert state.attributes["pollutant_assessments"]["pm25"]["severity"] == (
        AirQualityState.UNKNOWN
    )
    assert state.attributes["pollutant_assessments"]["pm25"]["provisional_alert"]
    assert {
        "comfort",
        "humidity",
        "mould_risk",
        "pollutant_state",
        "indoor_pollutant_measurements",
        "ventilation_demand",
        "air_exchange_suitability",
        "ventilation_strategy",
        "window_recommendation",
        "air_cleaning_recommendation",
        "available_capabilities",
        "context",
        # Deprecated aliases remain part of the compatibility contract.
        "pollutant_measurements",
        "pollutant_assessments",
    } <= set(state.attributes)
    assert "ignored_sources" not in state.attributes
    assert "PM2.5" in state.attributes["context"]
    assert all(
        isinstance(entity_id, str) for entity_id in state.attributes["source_entities"]
    )
    assert "comfort_quality" not in state.attributes
    assert "comfort_confidence" not in state.attributes
    assert "thermal_input_quality" not in state.attributes
    assert "temperature" not in state.attributes
    assert "relative_humidity" not in state.attributes
    assert "outdoor_temperature" not in state.attributes
    assert "outdoor_relative_humidity" not in state.attributes
    assert "decision_context" not in state.attributes
    assert "room_usage" not in state.attributes
    assert "cleaning_recommendation" not in state.attributes
    assert "surface_temperature" not in state.attributes
    assert "surface_relative_humidity" not in state.attributes
    for removed in (
        "temperature_state",
        "humidity_comfort_state",
        "combined_comfort",
        "ventilation",
        "apparent_temperature",
        "thermal_profile",
        "dew_point",
        "absolute_humidity",
        "humidity_ratio",
        "enthalpy",
        "mould_quality",
        "mould_warning_duration_seconds",
        "humidity_warning_duration_seconds",
        "outdoor_humidity_ratio",
        "outdoor_enthalpy",
        "outdoor_pollutant_assessments",
        "pollutant_comparisons",
    ):
        assert removed not in state.attributes

    await shutdown_integration(hass, [entry])


async def test_manual_category_creates_reference_temperature_number(
    hass: HomeAssistant,
) -> None:
    """Manual category exposes a restorable half-degree thermal reference."""
    temperature = MockSensor(
        name="manual_temperature",
        unique_id="manual_temperature_runtime",
        native_value=20,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        unit_of_measurement=UnitOfTemperature.CELSIUS,
    )
    await setup_mock_entities(hass, "sensor", {DEFAULT_MOCK_AREA: [temperature]})
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    data.update(
        {
            CONF_ENABLED_FEATURES: {CONF_FEATURE_ENVIRONMENT: {}},
            CONF_AREA_TEMPERATURE_SENSOR: temperature.entity_id,
            CONF_ROOM_CATEGORY: RoomCategory.MANUAL,
        }
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=data,
        version=AdaptiveConfigEntryVersion.MAJOR,
        minor_version=AdaptiveConfigEntryVersion.MINOR,
    )
    await init_integration(hass, [entry])

    entity_id = (
        f"number.adaptive_areas_environment_reference_temperature_"
        f"{DEFAULT_MOCK_AREA}"
    )
    reference = hass.states.get(entity_id)
    assert reference is not None
    assert reference.state == "20.0"
    assert reference.attributes["step"] == 0.5

    await hass.services.async_call(
        "number",
        "set_value",
        {ATTR_ENTITY_ID: entity_id, "value": 23.0},
        blocking=True,
    )

    area = hass.data[MODULE_DATA][entry.entry_id][DATA_AREA_OBJECT]
    assert area.environment is not None
    assert (
        area.environment.assessment["thermal_profile"]["reference_temperature"] == 23.0
    )
    assert area.environment.assessment["comfort"] == ComfortState.COOL

    await shutdown_integration(hass, [entry])


async def test_room_climate_enable_disable_reload(hass: HomeAssistant) -> None:
    """Feature reload creates and removes engine, listeners, and entity."""
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    entry = MockConfigEntry(domain=DOMAIN, data=data, version=2, minor_version=5)
    await init_integration(hass, [entry])
    entity_id = f"sensor.adaptive_areas_environment_{DEFAULT_MOCK_AREA}"
    assert hass.states.get(entity_id) is None

    hass.config_entries.async_update_entry(
        entry,
        options={**data, CONF_ENABLED_FEATURES: {CONF_FEATURE_ENVIRONMENT: {}}},
    )
    await hass.async_block_till_done()
    area = hass.data[MODULE_DATA][entry.entry_id][DATA_AREA_OBJECT]
    assert area.environment is not None
    assert hass.states.get(entity_id) is not None

    hass.config_entries.async_update_entry(
        entry, options={**data, CONF_ENABLED_FEATURES: {}}
    )
    await hass.async_block_till_done()
    area = hass.data[MODULE_DATA][entry.entry_id][DATA_AREA_OBJECT]
    assert area.environment is None
    assert hass.states.get(entity_id) is None

    await shutdown_integration(hass, [entry])


async def test_primary_sources_recover_without_reload(hass: HomeAssistant) -> None:
    """Unavailable primary sources trigger evaluation when each becomes valid."""
    area = _area(
        hass,
        {
            CONF_AREA_TEMPERATURE_SENSOR: "sensor.primary_temperature",
            CONF_AREA_HUMIDITY_SENSOR: "sensor.primary_humidity",
        },
    )
    attributes = {ATTR_DEVICE_CLASS: SensorDeviceClass.TEMPERATURE}
    hass.states.async_set("sensor.primary_temperature", STATE_UNAVAILABLE, attributes)
    hass.states.async_set(
        "sensor.primary_humidity",
        STATE_UNAVAILABLE,
        {ATTR_DEVICE_CLASS: SensorDeviceClass.HUMIDITY},
    )
    area.entities["sensor"] = [
        {ATTR_ENTITY_ID: "sensor.primary_temperature"},
        {ATTR_ENTITY_ID: "sensor.primary_humidity"},
    ]
    engine = AreaEnvironmentEngine(area)
    assert engine.assessment["state"] == EnvironmentState.UNKNOWN

    hass.states.async_set("sensor.primary_temperature", "21.5", attributes)
    await hass.async_block_till_done()
    assert engine.assessment["temperature"] == 21.5
    assert engine.assessment["relative_humidity"] is None
    assert engine.assessment["state"] == EnvironmentState.GOOD

    hass.states.async_set(
        "sensor.primary_humidity",
        "50",
        {ATTR_DEVICE_CLASS: SensorDeviceClass.HUMIDITY},
    )
    await hass.async_block_till_done()
    assert engine.assessment["relative_humidity"] == 50
    assert engine.assessment["thermal_input_quality"] == "enhanced"
    engine.unload()


async def test_regular_exterior_does_not_create_room_climate_sensor(
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


async def test_enabled_exterior_publishes_reduced_area_climate_sensor(
    hass: HomeAssistant,
) -> None:
    """Enabled exterior Area Climate exposes measurements without action fields."""
    temperature = MockSensor(
        name="garden_temperature",
        unique_id="garden_temperature_runtime",
        native_value=18,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        unit_of_measurement=UnitOfTemperature.CELSIUS,
    )
    humidity = MockSensor(
        name="garden_humidity",
        unique_id="garden_humidity_runtime",
        native_value=55,
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement="%",
        unit_of_measurement="%",
    )
    await setup_mock_entities(
        hass, "sensor", {DEFAULT_MOCK_AREA: [temperature, humidity]}
    )
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    data.update(
        {
            CONF_TYPE: AREA_TYPE_EXTERIOR,
            CONF_ENABLED_FEATURES: {CONF_FEATURE_ENVIRONMENT: {}},
            CONF_AREA_TEMPERATURE_SENSOR: temperature.entity_id,
            CONF_AREA_HUMIDITY_SENSOR: humidity.entity_id,
        }
    )
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    await init_integration(hass, [entry])

    area = hass.data[MODULE_DATA][entry.entry_id][DATA_AREA_OBJECT]
    state = hass.states.get(f"sensor.adaptive_areas_environment_{DEFAULT_MOCK_AREA}")
    assert area.environment is not None
    assert state is not None
    assert state.attributes["temperature"] == 18
    assert state.attributes["relative_humidity"] == 55
    for absent in (
        "comfort",
        "ventilation",
        "ventilation_state",
        "ventilation_demand",
        "ventilation_activity",
        "cooling",
        "air_exchange_suitability",
        "window_recommendation",
        "ventilation_fan_request",
        "circulation_fan_request",
    ):
        assert absent not in state.attributes

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

    assert entry.minor_version == 12
    assert entry.data[CONF_ENABLED_FEATURES][CONF_FEATURE_ENVIRONMENT] == {}
    assert entry.data[CONF_ENVIRONMENT_OUTDOOR_TEMPERATURE] == "sensor.outdoor"
    assert entry.data[CONF_ENVIRONMENT_CIRCULATION_FANS] == ["fan.room"]
    assert CONF_ENVIRONMENT_COMFORT_MIN not in entry.data
    assert CONF_ENVIRONMENT_COMFORT_MAX not in entry.data
    assert entry.data[CONF_ROOM_CATEGORY] == RoomCategory.LIVING_SEDENTARY
    assert entry.options[CONF_ENABLED_FEATURES][CONF_FEATURE_ENVIRONMENT] == {}
    assert entry.options[CONF_ENVIRONMENT_WINDOWS] == ["binary_sensor.window"]
    assert CONF_ENVIRONMENT_COMFORT_MIN not in entry.options

    await shutdown_integration(hass, [entry])


async def test_rc5_primary_source_migration_is_conservative(
    hass: HomeAssistant,
) -> None:
    """One candidate is selected; ambiguous and excluded candidates are not."""
    async_get_area_registry(hass).async_create(name="Kitchen")
    temperature = MockSensor(
        name="only_temperature",
        unique_id="only_temperature",
        native_value=21,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        unit_of_measurement=UnitOfTemperature.CELSIUS,
    )
    humidity_a = MockSensor(
        name="humidity_a",
        unique_id="humidity_a",
        native_value=50,
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement="%",
        unit_of_measurement="%",
    )
    humidity_b = MockSensor(
        name="humidity_b",
        unique_id="humidity_b",
        native_value=55,
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement="%",
        unit_of_measurement="%",
    )
    await setup_mock_entities(
        hass,
        "sensor",
        {DEFAULT_MOCK_AREA: [temperature, humidity_a, humidity_b]},
    )
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    data[CONF_EXCLUDE_ENTITIES] = [humidity_b.entity_id]
    entry = MockConfigEntry(domain=DOMAIN, data=data, version=2, minor_version=3)

    migrated_data, migrated_options, data_changed, options_changed = (
        _migrate_primary_area_sources(hass, entry, data, {})
    )

    assert migrated_data[CONF_AREA_TEMPERATURE_SENSOR] == temperature.entity_id
    assert migrated_data[CONF_AREA_HUMIDITY_SENSOR] == humidity_a.entity_id
    assert migrated_options == {}
    assert data_changed is True
    assert options_changed is False

    data[CONF_EXCLUDE_ENTITIES] = []
    ambiguous, _, _, _ = _migrate_primary_area_sources(hass, entry, data, {})
    assert CONF_AREA_HUMIDITY_SENSOR not in ambiguous


async def test_rc6_migration_keeps_evaluation_disabled(hass: HomeAssistant) -> None:
    """RC6 intrinsic entity is not proof of explicit feature intent."""
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    data.update(
        {
            CONF_AREA_TEMPERATURE_SENSOR: "sensor.saved_temperature",
            CONF_ENVIRONMENT_OUTDOOR_TEMPERATURE: "sensor.saved_outdoor",
            CONF_ROOM_CATEGORY: RoomCategory.SLEEPING_REST,
        }
    )
    entry = MockConfigEntry(domain=DOMAIN, data=data, version=2, minor_version=4)
    await init_integration(hass, [entry])

    assert entry.minor_version == 12
    assert CONF_FEATURE_ENVIRONMENT not in entry.data[CONF_ENABLED_FEATURES]
    assert entry.data[CONF_AREA_TEMPERATURE_SENSOR] == "sensor.saved_temperature"
    assert entry.data[CONF_ENVIRONMENT_OUTDOOR_TEMPERATURE] == "sensor.saved_outdoor"
    area = hass.data[MODULE_DATA][entry.entry_id][DATA_AREA_OBJECT]
    assert area.environment is None

    await shutdown_integration(hass, [entry])


async def test_legacy_room_usage_toggle_migrates_to_independent_feature(
    hass: HomeAssistant,
) -> None:
    """Legacy General toggle enables Room Usage and is removed from storage."""
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    data[CONF_TRACK_ROOM_USAGE] = True
    entry = MockConfigEntry(domain=DOMAIN, data=data, version=2, minor_version=5)

    await init_integration(hass, [entry])

    assert entry.minor_version == 12
    assert CONF_TRACK_ROOM_USAGE not in entry.data
    area = hass.data[MODULE_DATA][entry.entry_id][DATA_AREA_OBJECT]
    assert CONF_FEATURE_ROOM_USAGE in area.config[CONF_ENABLED_FEATURES]
    assert area.room_usage is not None
    assert area.environment is None
    assert (
        hass.states.get(f"sensor.adaptive_areas_room_usage_{DEFAULT_MOCK_AREA}")
        is not None
    )

    await shutdown_integration(hass, [entry])


def test_legacy_room_usage_storage_migration() -> None:
    """Legacy Room Usage storage becomes a feature marker."""
    data = {
        CONF_ENABLED_FEATURES: {CONF_FEATURE_ENVIRONMENT: {}},
        CONF_TRACK_ROOM_USAGE: True,
    }

    migrated, options, data_changed, options_changed = _migrate_room_usage_feature(
        data, {}
    )

    assert CONF_TRACK_ROOM_USAGE not in migrated
    assert set(migrated[CONF_ENABLED_FEATURES]) == {
        CONF_FEATURE_ENVIRONMENT,
        CONF_FEATURE_ROOM_USAGE,
    }
    assert migrated[CONF_ENABLED_FEATURES][CONF_FEATURE_ROOM_USAGE] == {
        CONF_PRESENCE_MINUTES_TO_DUE: DEFAULT_PRESENCE_MINUTES_TO_DUE
    }
    assert options == {}
    assert data_changed is True
    assert options_changed is False


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
        CONF_FEATURE_ENVIRONMENT: {},
    }
    data[CONF_ENVIRONMENT_CIRCULATION_FANS] = [fan.entity_id]
    data[CONF_AREA_TEMPERATURE_SENSOR] = temperature.entity_id
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
    assert environment_state.attributes["reason_codes"] == [
        "primary_humidity_sensor_not_configured",
        "room_too_warm",
        "outdoor_air_quality_unknown",
    ]
    assert environment_state.attributes["context"]

    await shutdown_integration(hass, [entry])


def test_environment_translation_value_coverage() -> None:
    """English and German translate every Environment state and attribute value."""
    translations = Path("custom_components/adaptive_areas/translations")
    expected_attribute_names = {
        "en": {
            "ventilation_fan_request": "Fan need",
            "circulation_fan_request": "Air circulation need",
            "moisture_ventilation": "Dehumidification by ventilation",
            "ventilation_strategy": "Ventilation strategy",
            "air_cleaning_recommendation": "Air cleaning recommendation",
            "indoor_source_entities": "Indoor source entities",
            "outdoor_source_entities": "Outdoor source entities",
            "source_entities": "Entities used",
        },
        "de": {
            "ventilation_fan_request": "Lüfterbedarf",
            "circulation_fan_request": "Umluftbedarf",
            "moisture_ventilation": "Entfeuchtung durch Lüften",
            "ventilation_strategy": "Lüftungsstrategie",
            "air_cleaning_recommendation": "Luftreinigungsempfehlung",
            "indoor_source_entities": "Innenraum-Quellentitäten",
            "outdoor_source_entities": "Außenluft-Quellentitäten",
            "source_entities": "Verwendete Entitäten",
        },
    }
    expected_values = {
        "comfort": {str(state) for state in ComfortState},
        "temperature_state": {str(state) for state in ComfortState},
        "humidity_comfort_state": {str(state) for state in HumidityState},
        "combined_comfort": {str(state) for state in CombinedComfortState},
        "room_category": {str(category) for category in RoomCategory} | {"unknown"},
        "humidity": {str(state) for state in HumidityState},
        "mould_risk": {str(state) for state in MouldRiskState},
        "mould_quality": {"surface_based", "room_air_estimate", "unknown"},
        "air_quality": {str(state) for state in AirQualityState},
        "pollutant_state": {str(state) for state in PollutantState},
        "ventilation": {str(state) for state in VentilationState},
        "ventilation_demand": {str(state) for state in VentilationDemand},
        "ventilation_strategy": {str(state) for state in VentilationStrategy},
        "air_cleaning_recommendation": {
            str(state) for state in AirCleaningRecommendation
        },
        "ventilation_activity": {str(state) for state in VentilationActivity},
        "cooling": {str(state) for state in CoolingState},
        "window_recommendation": {str(state) for state in WindowRecommendation},
        "ventilation_fan_request": {str(state) for state in VentilationFanRequest},
        "circulation_fan_request": {str(state) for state in CirculationFanRequest},
        "moisture_ventilation": {"favorable", "unfavorable", "unknown"},
        "air_exchange_suitability": {str(state) for state in AirExchangeSuitability},
        "dominant_indoor_pollutant": {
            "co2",
            "pm25",
            "pm10",
            "co",
            "no2",
            "ozone",
            "voc",
            "unknown",
        },
        "available_capabilities": {
            "temperature",
            "humidity",
            "co2",
            "pm25",
            "pm10",
            "pm1",
            "voc",
            "voc_parts",
            "aqi",
            "co",
            "no2",
            "ozone",
            "ventilation_fans",
            "windows",
            "outdoor_temperature",
            "outdoor_humidity",
            "surface_temperature",
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
        "outdoor_humidity_ratio",
        "outdoor_enthalpy",
        "pollutant_measurements",
        "pollutant_assessments",
        "indoor_pollutant_measurements",
        "indoor_pollutant_assessments",
        "pollutant_comparisons",
        "outdoor_pollutant_measurements",
        "outdoor_pollutant_assessments",
        "source_entities",
        "indoor_source_entities",
        "outdoor_source_entities",
        "ignored_sources",
        "humidity_warning_duration_seconds",
        "context",
        "indoor_reason_codes",
        "mitigation_reason_codes",
    }

    for language in ("en", "de"):
        content = json.loads((translations / f"{language}.json").read_text())
        environment = content["entity"]["sensor"]["environment"]
        assert environment["name"] == (
            "Area Climate" if language == "en" else "Bereichsklima"
        )
        assert set(environment["state"]) == {str(state) for state in EnvironmentState}
        assert set(expected_values) | named_only <= set(environment["state_attributes"])
        for attribute, name in expected_attribute_names[language].items():
            assert environment["state_attributes"][attribute]["name"] == name
        for attribute, values in expected_values.items():
            translation = environment["state_attributes"][attribute]
            assert translation["name"]
            assert set(translation["state"]) == values
            assert all(translation["state"].values())
        usage = content["entity"]["sensor"]["room_usage"]
        assert set(usage["state_attributes"]) == {
            "cumulative_presence_seconds",
            "presence_minutes_to_due",
            "current_occupancy_duration_seconds",
            "last_cleaned",
        }
        due = content["entity"]["binary_sensor"]["cleaning_due"]
        assert set(due["state"]) == {"off", "on"}
        serialized = json.dumps(content)
        assert "Area Evaluation" not in serialized
        assert "Bereichsauswertung" not in serialized
        assert "Environmental Sensors" not in serialized
        assert "Umweltsensoren" not in serialized
