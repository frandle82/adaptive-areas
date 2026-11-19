"""Test initializing the system."""

import logging
from unittest.mock import patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.components.binary_sensor import DOMAIN as BINARY_SENSOR_DOMAIN
from homeassistant.const import STATE_OFF
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import async_get as async_get_device_registry
from homeassistant.helpers.entity_registry import (
    RegistryEntryDisabler,
    async_get as async_get_entity_registry,
)

from custom_components.adaptive_areas.const import (
    CONF_AREAS,
    CONF_ENABLED_FEATURES,
    CONF_FEATURE_ROOM_USAGE,
    CONF_PRESENCE_MINUTES_TO_DUE,
    CONF_PRESENCE_SECONDS_TO_DUE,
    DATA_AREA_OBJECT,
    DOMAIN,
    MODULE_DATA,
)
from custom_components.adaptive_areas.helpers.area import get_runtime_areas_for_entry
from custom_components.adaptive_areas.helpers.area import (
    transfer_area_devices_to_container,
    transfer_area_entities_to_container,
)

from tests.const import DEFAULT_MOCK_AREA, MockAreaIds
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


async def test_global_entry_sets_up_all_runtime_areas(
    hass: HomeAssistant,
) -> None:
    """A GlobalEntry loads each configured Area while forwarding platforms once."""
    area_ids = [
        MockAreaIds.KITCHEN,
        MockAreaIds.LIVING_ROOM,
        MockAreaIds.MASTER_BEDROOM,
    ]
    areas = {
        area_id.value: get_basic_config_entry_data(area_id) for area_id in area_ids
    }
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=get_basic_config_entry_data(MockAreaIds.GLOBAL),
        options={CONF_AREAS: areas},
        version=2,
        minor_version=11,
    )

    with patch.object(
        hass.config_entries,
        "async_forward_entry_setups",
        wraps=hass.config_entries.async_forward_entry_setups,
    ) as forward_setups:
        await init_integration(hass, [entry], areas=area_ids)

    forward_setups.assert_awaited_once()
    assert {str(platform) for platform in forward_setups.await_args.args[1]} >= {
        "sensor",
        "binary_sensor",
        "switch",
    }

    runtime_areas = get_runtime_areas_for_entry(hass, entry)
    assert [area.id for area in runtime_areas] == sorted(areas)
    assert len(hass.data[MODULE_DATA][entry.entry_id][CONF_AREAS]) == 3
    for area_id in area_ids:
        assert (
            hass.states.get(
                f"{BINARY_SENSOR_DOMAIN}.adaptive_areas_presence_tracking_"
                f"{area_id.value}_area_state"
            )
            is not None
        )

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.entry_id not in hass.data.get(MODULE_DATA, {})

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert len(get_runtime_areas_for_entry(hass, entry)) == 3

    await shutdown_integration(hass, [entry])
    assert entry.entry_id not in hass.data.get(MODULE_DATA, {})


async def test_registry_ownership_transfer_preserves_area_identity(
    hass: HomeAssistant,
    basic_config_entry: MockConfigEntry,
    _setup_integration_basic,
) -> None:
    """Ownership transfer retains generated entity and device identity unchanged."""
    area = hass.data[MODULE_DATA][basic_config_entry.entry_id][DATA_AREA_OBJECT]
    entity_id = f"{BINARY_SENSOR_DOMAIN}.adaptive_areas_presence_tracking_{area.slug}_area_state"
    entity_registry = async_get_entity_registry(hass)
    original = entity_registry.async_get(entity_id)
    assert original is not None
    assert original.device_id is not None

    entity_registry.async_update_entity(
        entity_id,
        name="My custom presence",
        disabled_by=RegistryEntryDisabler.USER,
        area_id=area.id,
    )
    device_registry = async_get_device_registry(hass)
    device_registry.async_update_device(original.device_id, area_id=area.id)

    global_entry = MockConfigEntry(domain=DOMAIN)
    global_entry.add_to_hass(hass)
    global_entry_id = global_entry.entry_id
    assert transfer_area_entities_to_container(
        hass,
        old_entry_id=basic_config_entry.entry_id,
        global_entry_id=global_entry_id,
        area=area,
    ) == [entity_id]
    assert transfer_area_devices_to_container(
        hass,
        old_entry_id=basic_config_entry.entry_id,
        global_entry_id=global_entry_id,
        area_id=area.id,
    ) == [original.device_id]

    transferred = entity_registry.async_get(entity_id)
    assert transferred is not None
    assert transferred.config_entry_id == global_entry_id
    assert transferred.unique_id == original.unique_id
    assert transferred.name == "My custom presence"
    assert transferred.disabled_by == RegistryEntryDisabler.USER
    assert transferred.area_id == area.id
    device = device_registry.async_get(original.device_id)
    assert device is not None
    assert device.id == original.device_id
    assert device.area_id == area.id
    assert device.config_entry_id == global_entry_id
    assert device.config_entry_id != basic_config_entry.entry_id


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
