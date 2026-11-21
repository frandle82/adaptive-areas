"""Area options that the central editor does not edit survive a partial save (step 6.1)."""

from custom_components.adaptive_areas.area_config import validate_area_options
from custom_components.adaptive_areas.const import (
    CONF_AREA_HUMIDITY_SENSOR,
    CONF_AREA_TEMPERATURE_SENSOR,
    CONF_CLEAR_TIMEOUT,
    CONF_ENVIRONMENT_CIRCULATION_FANS,
    CONF_ENVIRONMENT_DISABLED_FANS,
    CONF_ENVIRONMENT_HUMIDITY_DURATION,
    CONF_ENVIRONMENT_OUTDOOR_HUMIDITY,
    CONF_ENVIRONMENT_OUTDOOR_TEMPERATURE,
    CONF_ENVIRONMENT_PASSIVE_COOLING_DELTA,
    CONF_ENVIRONMENT_SURFACE_TEMPERATURE,
    CONF_ENVIRONMENT_VENTILATION_FANS,
    CONF_ENVIRONMENT_WINDOWS,
    CONF_ROOM_CATEGORY,
    CONF_TYPE,
)

# Fields that the panel does not edit (see docs/specifications/dashboard-migration-matrix.md §13).
NOT_EDITED = {
    CONF_AREA_TEMPERATURE_SENSOR: "sensor.area_temp",
    CONF_AREA_HUMIDITY_SENSOR: "sensor.area_humidity",
    CONF_ROOM_CATEGORY: "living_sedentary",
    CONF_ENVIRONMENT_OUTDOOR_TEMPERATURE: "sensor.outdoor_temp",
    CONF_ENVIRONMENT_OUTDOOR_HUMIDITY: "sensor.outdoor_humidity",
    CONF_ENVIRONMENT_SURFACE_TEMPERATURE: "sensor.surface_temp",
    CONF_ENVIRONMENT_WINDOWS: ["binary_sensor.window"],
    CONF_ENVIRONMENT_PASSIVE_COOLING_DELTA: 3.0,
    CONF_ENVIRONMENT_HUMIDITY_DURATION: 30,
    CONF_ENVIRONMENT_VENTILATION_FANS: ["fan.vent"],
    CONF_ENVIRONMENT_CIRCULATION_FANS: ["fan.circ"],
    CONF_ENVIRONMENT_DISABLED_FANS: ["fan.off"],
}


def _current() -> dict:
    options, errors = validate_area_options(
        {CONF_TYPE: "interior", CONF_CLEAR_TIMEOUT: 5, **NOT_EDITED}, {}
    )
    assert errors == {}
    return options


def test_partial_save_keeps_every_field_the_panel_does_not_edit() -> None:
    """A save that sends only edited fields keeps the hidden environment configuration."""
    stored = _current()
    saved, errors = validate_area_options(stored, {CONF_CLEAR_TIMEOUT: 9})

    assert errors == {}
    assert saved[CONF_CLEAR_TIMEOUT] == 9
    for key, value in NOT_EDITED.items():
        assert saved[key] == value, key


def test_explicit_empty_value_is_still_an_explicit_change() -> None:
    """Clearing an optional sensor is an explicit update, not a silent omission."""
    saved, errors = validate_area_options(
        _current(), {CONF_AREA_TEMPERATURE_SENSOR: ""}
    )

    assert errors == {}
    assert saved[CONF_AREA_TEMPERATURE_SENSOR] == ""
    assert saved[CONF_AREA_HUMIDITY_SENSOR] == NOT_EDITED[CONF_AREA_HUMIDITY_SENSOR]


def test_removed_optional_keys_are_not_restored_by_the_merge() -> None:
    """A feature dictionary sent whole replaces the stored one; removed keys stay removed."""
    stored = {
        CONF_TYPE: "interior",
        "features": {
            "light": {
                "turn_on_below": 50.0,
                "turn_off_above": 200.0,
                "vacancy_delay": 30,
            },
            "climate_control": {
                "entity_id": "climate.kitchen",
                "preset_clear": "off",
                "climate_occupancy_threshold": 5,
            },
        },
    }
    updates = {
        "features": {
            "light": {"turn_on_below": 50.0, "turn_off_above": 200.0},
            "climate_control": {"preset_clear": "off"},
        }
    }
    saved, errors = validate_area_options(stored, updates)

    assert errors == {}
    assert "vacancy_delay" not in saved["features"]["light"]
    assert "entity_id" not in saved["features"]["climate_control"]
    # Removing the key does not restore the stored value; the schema default applies.
    assert saved["features"]["climate_control"]["climate_occupancy_threshold"] == 10
    assert saved["features"]["climate_control"]["preset_clear"] == "off"


def test_zero_thresholds_and_empty_sensor_are_explicit_values() -> None:
    """0 is a valid threshold; an explicitly empty sensor is an explicit value, not missing."""
    saved, errors = validate_area_options(
        _current(),
        {
            "features": {
                "climate_control": {
                    "preset_clear": "off",
                    "climate_occupancy_threshold": 0,
                }
            },
            CONF_AREA_TEMPERATURE_SENSOR: "",
        },
    )

    assert errors == {}
    assert saved["features"]["climate_control"]["climate_occupancy_threshold"] == 0
    assert saved[CONF_AREA_TEMPERATURE_SENSOR] == ""
