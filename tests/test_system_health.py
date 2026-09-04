"""Tests for native Adaptive Areas System Health."""

import json

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.loader import async_get_integration

from custom_components.adaptive_areas.const import DOMAIN
from custom_components.adaptive_areas.system_health import async_system_health_info


async def test_system_health_summary_is_private(
    hass: HomeAssistant, basic_config_entry: MockConfigEntry, _setup_integration_basic
) -> None:
    """System Health exposes counts and never area or entity identifiers."""
    info = await async_system_health_info(hass)
    integration = await async_get_integration(hass, DOMAIN)
    assert info["version"] == integration.version
    assert info["configured_entries"] == 1
    assert info["loaded_entries"] == 1
    assert info["regular_areas"] == 1
    assert info["meta_areas"] == 0
    assert info["interior_areas"] == 1
    assert info["active_repairs"] == 1
    serialized = json.dumps(info)
    assert "kitchen" not in serialized.lower()
    assert "binary_sensor" not in serialized

    ir.async_create_issue(
        hass,
        DOMAIN,
        "test_issue",
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="missing_area",
    )
    info = await async_system_health_info(hass)
    assert info["active_repairs"] == 2
