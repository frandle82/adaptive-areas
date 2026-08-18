"""Test initializing the system."""

import logging

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.components.binary_sensor import DOMAIN as BINARY_SENSOR_DOMAIN
from homeassistant.const import STATE_OFF
from homeassistant.core import HomeAssistant

from custom_components.adaptive_areas.const import (
    CONF_ENABLED_FEATURES,
    CONF_FEATURE_ROOM_USAGE,
    CONF_ENVIRONMENT_MANUAL_PM25_SENSORS,
    CONF_ENVIRONMENT_MANUAL_PM25_UNIT,
    CONF_PRESENCE_MINUTES_TO_DUE,
    CONF_PRESENCE_SECONDS_TO_DUE,
    DOMAIN,
)

from tests.const import DEFAULT_MOCK_AREA
from tests.helpers import (
    assert_state,
    get_basic_config_entry_data,
    init_integration,
    shutdown_integration,
)

_LOGGER = logging.getLogger(__name__)


async def test_init_default_config(
    hass: HomeAssistant, basic_config_entry: MockConfigEntry, _setup_integration_basic
) -> None:
    """Test loading the integration."""

    # Validate the right enties were created.
    area_binary_sensor = hass.states.get(
        f"{BINARY_SENSOR_DOMAIN}.adaptive_areas_presence_tracking_kitchen_area_state"
    )

    assert_state(area_binary_sensor, STATE_OFF)


async def test_cleaning_threshold_migrates_from_seconds_to_minutes(
    hass: HomeAssistant,
) -> None:
    """Version 2.7 thresholds retain their duration using minute configuration."""
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=data,
        options={
            CONF_ENABLED_FEATURES: {
                CONF_FEATURE_ROOM_USAGE: {CONF_PRESENCE_SECONDS_TO_DUE: 7200}
            }
        },
        version=2,
        minor_version=7,
    )

    await init_integration(hass, [entry])

    assert entry.minor_version == 10
    feature_config = entry.options[CONF_ENABLED_FEATURES][CONF_FEATURE_ROOM_USAGE]
    assert feature_config[CONF_PRESENCE_MINUTES_TO_DUE] == 120
    assert CONF_PRESENCE_SECONDS_TO_DUE not in feature_config

    await shutdown_integration(hass, [entry])


async def test_pollutant_unit_schema_upgrade_preserves_manual_sources(
    hass: HomeAssistant,
) -> None:
    """Version 2.9 manual pollutant assignments survive the 2.10 upgrade."""
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=data,
        options={
            **data,
            CONF_ENVIRONMENT_MANUAL_PM25_SENSORS: ["sensor.example_pm25"],
            CONF_ENVIRONMENT_MANUAL_PM25_UNIT: "µg/m³",
        },
        version=2,
        minor_version=9,
    )

    await init_integration(hass, [entry])

    assert entry.minor_version == 10
    assert entry.options[CONF_ENVIRONMENT_MANUAL_PM25_SENSORS] == [
        "sensor.example_pm25"
    ]
    assert entry.options[CONF_ENVIRONMENT_MANUAL_PM25_UNIT] == "µg/m³"

    await shutdown_integration(hass, [entry])
