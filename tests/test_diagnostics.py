"""Tests for native Adaptive Areas diagnostics."""

import json

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from custom_components.adaptive_areas.const import (
    CONF_BLE_TRACKER_ENTITIES,
    CONF_ENABLED_FEATURES,
    CONF_FEATURE_BLE_TRACKERS,
    CONF_FEATURE_LIGHT_GROUPS,
    CONF_INCLUDE_ENTITIES,
    CONF_NOTIFICATION_DEVICES,
    CONF_PRESENCE_CONTROL_ENTITIES,
    DATA_AREA_OBJECT,
    DOMAIN,
    MODULE_DATA,
)
from custom_components.adaptive_areas.diagnostics import (
    async_get_config_entry_diagnostics,
    async_get_device_diagnostics,
)

from tests.const import DEFAULT_MOCK_AREA
from tests.helpers import get_basic_config_entry_data, init_integration


async def test_config_entry_diagnostics_sections_and_trace(
    hass: HomeAssistant, basic_config_entry: MockConfigEntry, _setup_integration_basic
) -> None:
    """Diagnostics expose stable sections and oldest-first trace history."""
    diagnostics = await async_get_config_entry_diagnostics(hass, basic_config_entry)
    assert set(diagnostics) == {
        "integration",
        "configuration",
        "area",
        "presence",
        "states",
        "features",
        "entities",
        "repairs",
        "decision_trace",
        "environment",
    }
    assert diagnostics["integration"]["name"] == "Adaptive Areas"
    integration = await async_get_integration(hass, DOMAIN)
    assert diagnostics["integration"]["version"] == integration.version
    assert diagnostics["area"]["primary_occupancy_state"] == "clear"
    assert diagnostics["decision_trace"] == []
    assert diagnostics["environment"] == {"enabled": False}

    area = hass.data[MODULE_DATA][basic_config_entry.entry_id][DATA_AREA_OBJECT]
    area.trace_decision(
        feature="light_groups",
        trigger="area_state_changed",
        decision="no_action",
        outcome="skipped",
        reason_codes=["control_disabled"],
    )
    diagnostics = await async_get_config_entry_diagnostics(hass, basic_config_entry)
    assert diagnostics["decision_trace"][0]["reason_codes"] == ["control_disabled"]


async def test_diagnostics_redact_sensitive_references(hass: HomeAssistant) -> None:
    """Representative personal, tracker, BLE, and media values never export."""
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    data.update(
        {
            CONF_INCLUDE_ENTITIES: ["person.andreas_secret"],
            CONF_PRESENCE_CONTROL_ENTITIES: ["device_tracker.andreas_phone_secret"],
            CONF_ENABLED_FEATURES: {
                CONF_FEATURE_LIGHT_GROUPS: {},
                CONF_FEATURE_BLE_TRACKERS: {
                    CONF_BLE_TRACKER_ENTITIES: ["sensor.aa_bb_cc_dd_ee_ff_secret_uuid"]
                },
                "area_aware_media_player": {
                    CONF_NOTIFICATION_DEVICES: ["media_player.private_bedroom"]
                },
            },
        }
    )
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    await init_integration(hass, [entry])
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    serialized = json.dumps(diagnostics)

    for secret in (
        "andreas_secret",
        "andreas_phone_secret",
        "aa_bb_cc_dd_ee_ff_secret_uuid",
        "private_bedroom",
        "AA:BB:CC:DD:EE:FF",
        "secret media title",
    ):
        assert secret not in serialized
    assert "person.<redacted>" not in serialized
    assert diagnostics["repairs"]["missing_entities"]["count"] == 4


async def test_device_diagnostics_use_config_entry_mapping(
    hass: HomeAssistant, basic_config_entry: MockConfigEntry, _setup_integration_basic
) -> None:
    """Device diagnostics reuse the stable one-device-per-entry mapping."""
    diagnostics = await async_get_device_diagnostics(hass, basic_config_entry, object())
    assert diagnostics["device"] == {"mapping": "adaptive_area_config_entry"}
