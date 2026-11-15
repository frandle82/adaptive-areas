"""Tests for the read-only Adaptive Areas dashboard DTOs."""

import json
from types import SimpleNamespace

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from unittest.mock import AsyncMock, Mock, patch

from custom_components.adaptive_areas.const import (
    AREA_STATE_BRIGHT,
    AREA_STATE_DARK,
    CONF_DARK_ENTITY,
    CONF_ENABLED_FEATURES,
    CONF_OVERHEAD_LIGHTS,
    DATA_AREA_OBJECT,
    MODULE_DATA,
)
from custom_components.adaptive_areas.dashboard import (
    build_area_detail,
    build_diagnostics,
    build_overview,
)
from custom_components.adaptive_areas.websocket import (
    _get_area,
    async_update_area,
    async_register_websocket_commands,
)
from custom_components.adaptive_areas.panel import async_setup_panel


async def test_dashboard_overview_is_empty_without_loaded_areas(
    hass: HomeAssistant,
) -> None:
    """A fresh system has a valid empty read-only payload."""
    overview = build_overview(hass)

    json.dumps(overview)
    assert overview == {
        "areas": [],
        "enabled_feature_tabs": [],
        "counts": {
            "areas": 0,
            "meta_areas": 0,
            "occupied": 0,
            "dark": 0,
            "bright": 0,
            "lights_on": 0,
        },
    }


async def test_dashboard_detail_handles_minimal_area(
    hass: HomeAssistant, basic_config_entry, _setup_integration_basic
) -> None:
    """An area without optional features remains serializable and explicit."""
    area = hass.data[MODULE_DATA][basic_config_entry.entry_id][DATA_AREA_OBJECT]

    detail = build_area_detail(hass, area)

    assert detail["id"] == area.id
    assert detail["type"] == "area"
    assert detail["presence"]["occupied"] is False
    assert detail["light_groups"] == []
    assert detail["environment"] is None
    assert detail["controls"] == []
    json.dumps(detail)
    assert {
        "adaptive_areas/get_overview",
        "adaptive_areas/get_area",
        "adaptive_areas/get_diagnostics",
        "adaptive_areas/subscribe_updates",
        "adaptive_areas/get_area_configuration",
        "adaptive_areas/create_area",
        "adaptive_areas/update_area",
        "adaptive_areas/delete_area",
    } <= set(hass.data["websocket_api"])


async def test_dashboard_area_update_validates_then_reloads_once(
    hass: HomeAssistant, basic_config_entry, _setup_integration_basic
) -> None:
    """Admin writes keep ConfigEntry options atomic and reload exactly once."""
    with patch.object(
        hass.config_entries, "async_reload", new_callable=AsyncMock
    ) as reload:
        errors = await async_update_area(
            hass,
            basic_config_entry,
            {CONF_ENABLED_FEATURES: {"environment": {}}},
        )

    assert errors == {}
    assert "environment" in basic_config_entry.options[CONF_ENABLED_FEATURES]
    reload.assert_awaited_once_with(basic_config_entry.entry_id)


async def test_dashboard_area_update_returns_field_errors_without_mutation(
    hass: HomeAssistant, basic_config_entry, _setup_integration_basic
) -> None:
    """Invalid panel values remain a recoverable form error."""
    original = dict(basic_config_entry.options)

    errors = await async_update_area(
        hass, basic_config_entry, {"clear_timeout": "not-a-number"}
    )

    assert "clear_timeout" in errors
    assert dict(basic_config_entry.options) == original


async def test_dashboard_area_update_cannot_change_regular_area_to_meta(
    hass: HomeAssistant, basic_config_entry, _setup_integration_basic
) -> None:
    """A ConfigEntry cannot be rebound to a different Area ownership model."""
    errors = await async_update_area(hass, basic_config_entry, {"type": "meta"})

    assert errors == {"type": "Area type cannot change to or from Meta"}


async def test_dashboard_controls_are_owned_deduplicated_and_json_safe(
    hass: HomeAssistant, basic_config_entry, _setup_integration_basic
) -> None:
    """Only configured area lights become safe, explicit control DTOs."""
    area = hass.data[MODULE_DATA][basic_config_entry.entry_id][DATA_AREA_OBJECT]
    light_id = "light.dashboard_control"
    hass.states.async_set(light_id, "off", {"friendly_name": "Desk light"})
    area.config[CONF_ENABLED_FEATURES] = {
        "light_groups": {CONF_OVERHEAD_LIGHTS: [light_id, light_id]}
    }

    detail = build_area_detail(hass, area)

    assert detail["controls"] == [
        {
            "id": CONF_OVERHEAD_LIGHTS,
            "name": "Overhead",
            "controls": [
                {
                    "entity_id": light_id,
                    "name": "Desk light",
                    "domain": "light",
                    "state": "off",
                    "available": True,
                    "controllable": True,
                    "actions": ["turn_on", "turn_off"],
                    "icon": None,
                }
            ],
        }
    ]
    json.dumps(detail["controls"])


async def test_dashboard_marks_meta_areas_and_reports_diagnostics(
    hass: HomeAssistant,
    all_areas_with_meta_config_entry,
    _setup_integration_all_areas_with_meta,
) -> None:
    """Meta areas are distinguishable and diagnostics are JSON-safe summaries."""
    overview = build_overview(hass)
    diagnostics = build_diagnostics(hass, "test")

    assert any(area["type"] == "meta" for area in overview["areas"])
    assert diagnostics["version"] == "test"
    assert diagnostics["area_count"] + diagnostics["meta_area_count"] == len(
        overview["areas"]
    )


async def test_dashboard_rejects_unknown_area(hass: HomeAssistant) -> None:
    """The detail endpoint helper does not manufacture a missing area."""
    with pytest.raises(HomeAssistantError, match="Adaptive Area not found"):
        _get_area(hass, "missing")


@pytest.mark.parametrize(
    ("dark_source_state", "area_state", "expected_warning"),
    [
        ("on", AREA_STATE_BRIGHT, False),
        ("off", AREA_STATE_DARK, False),
        ("on", AREA_STATE_DARK, True),
        ("off", AREA_STATE_BRIGHT, True),
        ("unavailable", AREA_STATE_DARK, False),
        ("unknown", AREA_STATE_BRIGHT, False),
    ],
)
async def test_dashboard_brightness_consistency_uses_available_dark_source_only(
    hass: HomeAssistant,
    basic_config_entry,
    _setup_integration_basic,
    dark_source_state: str,
    area_state: str,
    expected_warning: bool,
) -> None:
    """Only contradictory available dark sources produce a warning."""
    area = hass.data[MODULE_DATA][basic_config_entry.entry_id][DATA_AREA_OBJECT]
    entity_id = "binary_sensor.dashboard_dark_source"
    area.config[CONF_DARK_ENTITY] = entity_id
    area.states = [area_state]
    hass.states.async_set(entity_id, dark_source_state)

    diagnostics = build_diagnostics(hass, "test")

    assert (
        "brightness_state_inconsistent"
        in {issue["code"] for issue in diagnostics["issues"]}
    ) is expected_warning


async def test_panel_and_websocket_registration_are_idempotent(
    hass: HomeAssistant,
) -> None:
    """Panel setup registers one panel and one command set across entry reloads."""
    hass.config.components.add("frontend")
    hass.http = Mock(async_register_static_paths=AsyncMock())
    with (
        patch(
            "custom_components.adaptive_areas.panel.async_panel_exists",
            side_effect=(False, True),
        ),
        patch(
            "custom_components.adaptive_areas.panel.panel_custom.async_register_panel",
            new_callable=AsyncMock,
        ) as register_panel,
    ):
        await async_setup_panel(hass)
        await async_setup_panel(hass)

    hass.http.async_register_static_paths.assert_awaited_once()
    register_panel.assert_awaited_once()
    assert hass.data["adaptive_areas_dashboard_websocket_registered"] is True


class _DashboardConnection:
    """Minimal WebSocket connection exercising registered command handlers."""

    user = SimpleNamespace(is_admin=True)

    def __init__(self) -> None:
        self.result = None
        self.events = []
        self.subscriptions = {}

    def send_result(self, _msg_id, result=None) -> None:
        self.result = result

    def send_event(self, _msg_id, event) -> None:
        self.events.append(event)


async def _call_dashboard_command(
    hass: HomeAssistant, connection: _DashboardConnection, command: str
) -> None:
    """Call a command through HA's registered handler and schema."""
    handler, schema = hass.data["websocket_api"][command]
    message = {"id": 1, "type": command}
    handler(hass, connection, message if schema is False else schema(message))
    await hass.async_block_till_done()


async def test_dashboard_overview_websocket_command_returns_payload(
    hass: HomeAssistant, basic_config_entry, _setup_integration_basic
) -> None:
    """The registered overview command returns a successful runtime payload."""
    _ = basic_config_entry
    connection = _DashboardConnection()

    await _call_dashboard_command(hass, connection, "adaptive_areas/get_overview")

    assert connection.result is not None
    assert set(connection.result) == {"areas", "counts", "enabled_feature_tabs"}


async def test_dashboard_diagnostics_websocket_command_returns_payload(
    hass: HomeAssistant, basic_config_entry, _setup_integration_basic
) -> None:
    """The registered diagnostics command returns a successful runtime payload."""
    _ = basic_config_entry
    connection = _DashboardConnection()

    await _call_dashboard_command(hass, connection, "adaptive_areas/get_diagnostics")

    assert connection.result is not None
    assert connection.result["version"]
    assert connection.result["area_count"] == 1
    assert connection.result["warning_count"] == 0


async def test_dashboard_diagnostics_degrades_for_malformed_optional_data(
    hass: HomeAssistant, basic_config_entry, _setup_integration_basic
) -> None:
    """One malformed optional diagnostic value does not break the payload."""
    _ = basic_config_entry
    with patch(
        "custom_components.adaptive_areas.dashboard.build_area_detail",
        side_effect=ValueError,
    ):
        diagnostics = build_diagnostics(hass, "test")

    assert diagnostics["warning_count"] == 1
    assert diagnostics["issues"] == [
        {
            "severity": "warning",
            "area_id": str(basic_config_entry.data["id"]),
            "code": "diagnostics_unavailable",
            "message": "Some diagnostics are unavailable.",
        }
    ]


async def test_dashboard_diagnostics_reports_optional_source_and_aggregate_issues(
    hass: HomeAssistant, basic_config_entry, _setup_integration_basic
) -> None:
    """Unavailable sources and empty aggregates remain actionable diagnostics."""
    _ = basic_config_entry
    with patch(
        "custom_components.adaptive_areas.dashboard.build_area_detail",
        return_value={
            "id": str(basic_config_entry.data["id"]),
            "aggregates": [{"source_count": 0}],
            "brightness_detail": {"dark_source": None},
            "active_states": [],
            "sources": [{"available": False}],
        },
    ):
        diagnostics = build_diagnostics(hass, "test")

    assert diagnostics["empty_aggregate_count"] == 1
    assert diagnostics["unavailable_source_count"] == 1
    assert {issue["code"] for issue in diagnostics["issues"]} == {
        "empty_aggregate",
        "unavailable_source",
    }


async def test_dashboard_subscription_websocket_command_pushes_updates(
    hass: HomeAssistant, basic_config_entry, _setup_integration_basic
) -> None:
    """The registered subscription command listens only to dashboard entities."""
    _ = basic_config_entry
    connection = _DashboardConnection()

    await _call_dashboard_command(hass, connection, "adaptive_areas/subscribe_updates")
    assert connection.result is None
    assert connection.subscriptions

    area = hass.data[MODULE_DATA][basic_config_entry.entry_id][DATA_AREA_OBJECT]
    hass.states.async_set(
        f"binary_sensor.adaptive_areas_presence_tracking_{area.slug}_area_state",
        "on",
    )
    await hass.async_block_till_done()

    assert connection.events
    assert connection.events[0]["area"]["id"] == area.id


async def test_dashboard_empty_subscription_is_successful(hass: HomeAssistant) -> None:
    """No loaded Areas still produces a closable successful subscription."""
    async_register_websocket_commands(hass)
    connection = _DashboardConnection()

    await _call_dashboard_command(hass, connection, "adaptive_areas/subscribe_updates")

    assert connection.result is None
    connection.subscriptions[1]()
