"""Test initializing the system."""

import logging
from unittest.mock import patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.components.binary_sensor import DOMAIN as BINARY_SENSOR_DOMAIN
from homeassistant.const import STATE_OFF
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_registry import EVENT_ENTITY_REGISTRY_UPDATED

from custom_components.adaptive_areas.const import (
    CONF_ENABLED_FEATURES,
    CONF_FEATURE_ROOM_USAGE,
    CONF_PRESENCE_MINUTES_TO_DUE,
    CONF_PRESENCE_SECONDS_TO_DUE,
    DOMAIN,
    DATA_AREA_OBJECT,
    MODULE_DATA,
    SERVICE_MARK_CLEANED,
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


async def test_unload_removes_owned_resources_and_registry_listeners(
    hass: HomeAssistant, basic_config_entry: MockConfigEntry
) -> None:
    """Unload leaves no Area callbacks, shared services, or registry subscriber."""
    await init_integration(hass, [basic_config_entry])
    area = hass.data[MODULE_DATA][basic_config_entry.entry_id][DATA_AREA_OBJECT]

    with patch.object(
        hass.config_entries,
        "async_update_entry",
        wraps=hass.config_entries.async_update_entry,
    ) as update_entry:
        await shutdown_integration(hass, [basic_config_entry])
        update_entry.reset_mock()
        hass.bus.async_fire(
            EVENT_ENTITY_REGISTRY_UPDATED,
            {"action": "remove", "entity_id": "sensor.removed_after_unload"},
        )
        await hass.async_block_till_done()
        update_entry.assert_not_called()

    assert area._remove_load_listener is None
    assert area._remove_dispatcher_listener is None
    assert area._remove_reload_timer is None
    assert area.environment is None
    assert area.room_usage is None
    assert not hass.services.has_service(DOMAIN, SERVICE_MARK_CLEANED)


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

    assert entry.minor_version == 11
    feature_config = entry.options[CONF_ENABLED_FEATURES][CONF_FEATURE_ROOM_USAGE]
    assert feature_config[CONF_PRESENCE_MINUTES_TO_DUE] == 120
    assert CONF_PRESENCE_SECONDS_TO_DUE not in feature_config

    await shutdown_integration(hass, [entry])


async def test_pollutant_schema_upgrade_removes_manual_overrides(
    hass: HomeAssistant,
) -> None:
    """Version 2.10 pollutant type and unit overrides are removed in 2.11."""
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=data,
        options={
            **data,
            "manual_pm25_sensors": ["sensor.example_pm25"],
            "manual_pm25_unit": "µg/m³",
        },
        version=2,
        minor_version=10,
    )

    await init_integration(hass, [entry])

    assert entry.minor_version == 11
    assert "manual_pm25_sensors" not in entry.options
    assert "manual_pm25_unit" not in entry.options

    await shutdown_integration(hass, [entry])
