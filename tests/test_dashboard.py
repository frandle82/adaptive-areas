"""Tests for the read-only Adaptive Areas dashboard DTOs."""

import re

import json
from pathlib import Path
from time import monotonic
from types import SimpleNamespace

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.components.climate.const import ATTR_PRESET_MODE
from homeassistant.exceptions import HomeAssistantError
from unittest.mock import AsyncMock, Mock, patch

from custom_components.adaptive_areas.const import (
    AREA_STATE_BRIGHT,
    AREA_STATE_DARK,
    CONF_DARK_ENTITY,
    CONF_ENABLED_FEATURES,
    CONF_FEATURE_CLIMATE_CONTROL,
    CONF_FEATURE_LIGHT,
    CONF_CLIMATE_CONTROL_ENTITY_ID,
    CONF_CLIMATE_CONTROL_OCCUPANCY_THRESHOLD,
    CONF_CLIMATE_CONTROL_PRESET_CLEAR,
    CONF_CLIMATE_CONTROL_PRESET_OCCUPIED,
    CONF_OVERHEAD_LIGHTS,
    DATA_AREA_OBJECT,
    MODULE_DATA,
    AreaStates,
)
from custom_components.adaptive_areas.dashboard import (
    build_area_detail,
    build_climate_runtime_status,
    build_diagnostics,
    build_light_runtime_status,
    build_overview,
)

from custom_components.adaptive_areas.switch.climate_control import ClimateControlSwitch
from custom_components.adaptive_areas.helpers.light_override import (
    LightManualOverrideMode,
    LightManualOverrideState,
)
from custom_components.adaptive_areas.helpers.light_vacancy import LightVacancyState
from custom_components.adaptive_areas.helpers.sources import (
    LightSourceSnapshot,
    LightTargetSource,
)
from custom_components.adaptive_areas.websocket import (
    _get_area,
    async_update_area,
    async_register_websocket_commands,
)
from custom_components.adaptive_areas.panel import async_setup_panel

PICKER_SOURCE = (
    Path(__file__).parents[1]
    / "custom_components"
    / "adaptive_areas"
    / "frontend"
    / "aa-entity-picker.js"
)


def _dashboard_texts() -> str:
    """All visible dashboard texts (both languages): the native translation source (E7)."""
    import json as _json  # noqa: PLC0415
    from pathlib import Path as _Path  # noqa: PLC0415

    root = (
        _Path(__file__).parents[1]
        / "custom_components"
        / "adaptive_areas"
        / "dashboard_texts"
    )
    return " ".join(
        _json.dumps(
            _json.loads((root / f"{lang}.json").read_text(encoding="utf-8")),
            ensure_ascii=False,
        )
        for lang in ("en", "de")
    )


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
            "physical_occupied": 0,
            "physical_clear": 0,
            "physical_unknown": 0,
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
        "adaptive_areas/get_light_runtime_status",
        "adaptive_areas/get_climate_runtime_status",
        "adaptive_areas/create_area",
        "adaptive_areas/update_area",
        "adaptive_areas/delete_area",
    } <= set(hass.data["websocket_api"])


def test_light_runtime_status_is_read_only_and_handles_disabled_and_partial_policy(
    hass: HomeAssistant,
) -> None:
    """The form DTO reads a fresh source snapshot without requiring a manager."""
    disabled = SimpleNamespace(
        id="disabled",
        has_feature=lambda _feature: False,
    )
    assert build_light_runtime_status(hass, disabled) == {
        "area_id": "disabled",
        "light": {"enabled": False},
    }


def test_climate_runtime_status_reports_effective_runtime_state(
    hass: HomeAssistant,
) -> None:
    """Climate status exposes only effective, read-only control data."""
    states = [AreaStates.OCCUPIED]
    config = {
        CONF_CLIMATE_CONTROL_ENTITY_ID: "climate.test",
        CONF_CLIMATE_CONTROL_OCCUPANCY_THRESHOLD: 10,
        CONF_CLIMATE_CONTROL_PRESET_CLEAR: "away",
        CONF_CLIMATE_CONTROL_PRESET_OCCUPIED: "comfort",
    }
    area = SimpleNamespace(
        id="living",
        states=states,
        has_feature=lambda feature: feature == CONF_FEATURE_CLIMATE_CONTROL,
        feature_config=lambda _feature: config,
        has_state=lambda state: state in states,
    )
    controller = object.__new__(ClimateControlSwitch)
    controller.area = area
    controller._attr_is_on = True
    controller.preset_map = {
        AreaStates.CLEAR: "away",
        AreaStates.OCCUPIED: "comfort",
        AreaStates.SLEEP: "",
        AreaStates.EXTENDED: "",
    }
    controller.occupancy_threshold_minutes = 10
    controller._occupied_since = monotonic()
    area.climate_control_switch = controller
    hass.states.async_set("climate.test", "heat", {ATTR_PRESET_MODE: "comfort"})

    pending = build_climate_runtime_status(hass, area)

    assert pending == {
        "area_id": "living",
        "enabled": True,
        "controller_on": True,
        "target_entity": "climate.test",
        "target_available": True,
        "area_states": ["occupied"],
        "current_preset": "comfort",
        "occupancy_threshold": 10,
        "occupancy_pending": True,
        "decision": "no_action",
        "configured_preset": None,
    }

    controller._occupied_since = monotonic() - 601
    active = build_climate_runtime_status(hass, area)
    assert active["occupancy_pending"] is False
    assert active["decision"] == "occupied"
    assert active["configured_preset"] == "comfort"

    states[:] = [AreaStates.CLEAR]
    assert build_climate_runtime_status(hass, area)["decision"] == "clear"
    assert build_climate_runtime_status(hass, area)["configured_preset"] == "away"

    states[:] = [AreaStates.SLEEP]
    assert build_climate_runtime_status(hass, area)["decision"] == "no_action"
    assert build_climate_runtime_status(hass, area)["configured_preset"] is None

    controller._attr_is_on = False
    assert build_climate_runtime_status(hass, area)["controller_on"] is False
    assert build_climate_runtime_status(hass, area)["decision"] == "no_action"

    hass.states.async_set("climate.test", "unavailable")
    unavailable = build_climate_runtime_status(hass, area)
    assert unavailable["target_available"] is False
    assert unavailable["current_preset"] is None

    disabled = SimpleNamespace(
        id="disabled",
        states=[],
        has_feature=lambda _feature: False,
    )
    assert build_climate_runtime_status(hass, disabled) == {
        "area_id": "disabled",
        "enabled": False,
        "controller_on": False,
        "target_entity": None,
        "target_available": False,
        "area_states": [],
        "current_preset": None,
        "occupancy_threshold": None,
        "occupancy_pending": False,
        "decision": "no_action",
        "configured_preset": None,
    }

    empty = SimpleNamespace(
        id="empty",
        states=[],
        has_feature=lambda feature: feature == CONF_FEATURE_CLIMATE_CONTROL,
        feature_config=lambda _feature: {},
    )
    empty_status = build_climate_runtime_status(hass, empty)
    assert empty_status["enabled"] is True
    assert empty_status["target_entity"] is None
    assert empty_status["target_available"] is False
    assert empty_status["controller_on"] is False

    area = SimpleNamespace(
        id="living",
        has_feature=lambda feature: feature == CONF_FEATURE_LIGHT,
        feature_config=lambda _feature: {},
    )
    snapshot = LightSourceSnapshot(
        "living",
        (
            LightTargetSource("light.available", True),
            LightTargetSource("light.off", False),
        ),
        None,
        False,
        None,
        ("binary_sensor.presence",),
        True,
        True,
    )
    with patch(
        "custom_components.adaptive_areas.dashboard.light_source_snapshot",
        return_value=snapshot,
    ):
        status = build_light_runtime_status(hass, area)

    assert status["light"] == {
        "enabled": True,
        "presence": {"available": True, "occupied": True},
        "illuminance": {"configured": False, "available": False, "value": None},
        "policy": {"decision": "NO_ACTION", "reason": "policy_not_configured"},
        "override": {"mode": "NONE"},
        "vacancy": {"pending": False, "due_at": None},
        "targets": {"total": 2, "available": 1},
    }


def test_light_runtime_status_keeps_manager_state_area_local(
    hass: HomeAssistant,
) -> None:
    """Override and vacancy values come only from the requested Area manager."""
    manager = SimpleNamespace(
        override_state=LightManualOverrideState(LightManualOverrideMode.FORCE_ON, 1),
        vacancy_state=LightVacancyState(detected_at=10, due_at=40),
    )
    area = SimpleNamespace(
        id="living",
        light_runtime_manager=manager,
        has_feature=lambda feature: feature == CONF_FEATURE_LIGHT,
        feature_config=lambda _feature: {"turn_on_below": 100, "turn_off_above": 200},
    )
    snapshot = LightSourceSnapshot(
        "living", (), "sensor.lux", True, 120, (), False, None
    )
    with patch(
        "custom_components.adaptive_areas.dashboard.light_source_snapshot",
        return_value=snapshot,
    ):
        status = build_light_runtime_status(hass, area)

    assert status["light"]["override"] == {"mode": "FORCE_ON"}
    assert status["light"]["vacancy"] == {"pending": True, "due_at": 40}
    assert status["light"]["policy"] == {
        "decision": "NO_ACTION",
        "reason": "no_targets",
    }

    kitchen = SimpleNamespace(
        id="kitchen",
        light_runtime_manager=SimpleNamespace(
            override_state=LightManualOverrideState(
                LightManualOverrideMode.FORCE_OFF, 1
            ),
            vacancy_state=LightVacancyState(),
        ),
        has_feature=lambda feature: feature == CONF_FEATURE_LIGHT,
        feature_config=lambda _feature: {"turn_on_below": 100, "turn_off_above": 200},
    )
    with patch(
        "custom_components.adaptive_areas.dashboard.light_source_snapshot",
        return_value=snapshot,
    ):
        kitchen_status = build_light_runtime_status(hass, kitchen)

    assert kitchen_status["area_id"] == "kitchen"
    assert kitchen_status["light"]["override"] == {"mode": "FORCE_OFF"}
    assert kitchen_status["light"]["vacancy"] == {"pending": False, "due_at": None}


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
    assert "adaptive-areas-loader.js" in register_panel.call_args.kwargs["module_url"]
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
    hass: HomeAssistant, connection: _DashboardConnection, command: str, **data
) -> None:
    """Call a command through HA's registered handler and schema."""
    handler, schema = hass.data["websocket_api"][command]
    message = {"id": 1, "type": command, **data}
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


async def test_climate_runtime_status_websocket_handles_disabled_feature(
    hass: HomeAssistant, basic_config_entry, _setup_integration_basic
) -> None:
    """The Climate endpoint is safe for Areas without Climate Control."""
    area = hass.data[MODULE_DATA][basic_config_entry.entry_id][DATA_AREA_OBJECT]
    connection = _DashboardConnection()

    await _call_dashboard_command(
        hass,
        connection,
        "adaptive_areas/get_climate_runtime_status",
        area_id=str(area.id),
    )

    assert connection.result["area_id"] == str(area.id)
    assert connection.result["enabled"] is False
    assert connection.result["controller_on"] is False
    assert connection.result["target_entity"] is None
    assert connection.result["target_available"] is False

    area.config[CONF_ENABLED_FEATURES] = {
        CONF_FEATURE_CLIMATE_CONTROL: {
            CONF_CLIMATE_CONTROL_ENTITY_ID: "climate.test",
            CONF_CLIMATE_CONTROL_OCCUPANCY_THRESHOLD: 10,
        }
    }
    hass.states.async_set("climate.test", "heat", {ATTR_PRESET_MODE: "comfort"})
    await _call_dashboard_command(
        hass,
        connection,
        "adaptive_areas/get_climate_runtime_status",
        area_id=str(area.id),
    )

    assert connection.result["enabled"] is True
    assert connection.result["target_entity"] == "climate.test"
    assert connection.result["target_available"] is True
    assert connection.result["current_preset"] == "comfort"
    assert connection.result["occupancy_threshold"] == 10


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


def test_panel_keeps_vacancy_delay_and_renders_light_runtime_status() -> None:
    """The static panel keeps zero-capable config inputs beside the status block."""
    panel = Path(
        "custom_components/adaptive_areas/frontend/adaptive-areas-panel.js"
    ).read_text(encoding="utf-8")

    assert 'name="${prefix}vacancy_delay"' in panel
    assert 'light.vacancy_delay??""' in panel
    assert "adaptive_areas/get_light_runtime_status" in panel
    assert "Aktueller Status" in _dashboard_texts()


def test_panel_light_control_configuration_is_area_scoped() -> None:
    """The Light tab uses existing Area features and the Area update path."""
    panel = Path(
        "custom_components/adaptive_areas/frontend/adaptive-areas-panel.js"
    ).read_text(encoding="utf-8")

    assert "_lightAreas()" in panel
    assert "data-light-area" in panel
    assert "_renderLightGroupsConfiguration" in panel
    assert '_lightPolicyFields(t,features.light||{},"light:")' in panel
    assert "adaptive_areas/update_area" in panel
    # The Light tab is read-only and opens the central Area editor (step 6.8).
    assert "data-config-area" in panel
    assert "_saveLightConfiguration" not in panel
    assert "data-light-configuration" not in panel
    assert "await this._loadLightRuntime(area.area_id)" in panel
    # Light group values are written by the Light tab only, never by the Area form save.
    assert "light_group:${key}" not in panel
    assert 'this._value(form,"turn_on_below")' not in panel


def test_panel_climate_control_configuration_is_area_scoped() -> None:
    """The Climate tab exposes only real Climate Control configuration."""
    panel = Path(
        "custom_components/adaptive_areas/frontend/adaptive-areas-panel.js"
    ).read_text(encoding="utf-8")

    assert "_climateAreas()" in panel
    assert '"climate_control" in (area.options?.features||{})' in panel
    assert "data-climate-area" in panel
    assert "_climateControlTab(t)" in panel
    # The Climate tab is read-only and opens the central Area editor (step 6.8).
    assert "data-config-area" in panel
    assert "_saveClimateConfiguration" not in panel
    assert "data-climate-configuration" not in panel
    assert "_climateFromForm" in panel
    assert "_loadClimateRuntime(areaId)" in panel
    assert 'type:"adaptive_areas/get_climate_runtime_status",area_id:areaId' in panel
    assert "this._loadClimateRuntime(area.area_id)" in panel
    # Climate options come from the shared entity picker (domain filter), the live code path.
    assert 'domain="${escape(domain)}"' in panel
    assert 'commaList(this.getAttribute("domain"))' in PICKER_SOURCE.read_text(
        encoding="utf-8"
    )
    assert "climate:entity_id" in panel
    for key in (
        "preset_clear",
        "preset_occupied",
        "preset_sleep",
        "preset_extended",
        "climate_occupancy_threshold",
    ):
        assert f"climate:{key}" in panel
    for label in (
        "Klimasteuerung",
        "Thermostat",
        "Presets",
        "Preset bei freiem Bereich",
        "Preset bei Belegung",
        "Preset im Schlafzustand",
        "Preset im erweiterten Zustand",
        "Belegung nach",
        "Minuten",
        "Trage die Preset-Namen so ein, wie sie dein Thermostat bereitstellt.",
        "Aktueller Status",
        "Automatik",
        "Verfügbarkeit",
        "Bereichszustand",
        "Aktuelles Preset",
        "Gewähltes Preset",
        "Belegungsverzögerung",
        "Entscheidung",
        "Aktiv",
        "Inaktiv",
        "Verfügbar",
        "Nicht verfügbar",
        "Nicht konfiguriert",
        "wartet auf die Belegungsschwelle",
        "Aktueller Status derzeit nicht verfügbar.",
    ):
        assert label in _dashboard_texts()
    for value in (
        'clear:"Frei"',
        'sleep:"Schlafzustand"',
        'extended:"Erweiterter Zustand"',
        'occupied:"Belegt"',
        'clear:"Freier Bereich"',
        'occupied:"Belegung"',
        'no_action:"Keine automatische Aktion"',
    ):
        label_value = value.split(':"', 1)[1][:-1]
        assert f'"{label_value}"' in _dashboard_texts()
    assert "adaptive_areas/update_area" in panel


def test_panel_light_groups_uses_current_runtime_configuration() -> None:
    """The Light Groups editor renders current, not legacy, configuration keys."""
    panel = Path(
        "custom_components/adaptive_areas/frontend/adaptive-areas-panel.js"
    ).read_text(encoding="utf-8")

    assert '["overhead",this._t.lgOverhead]' in panel
    assert '["sleep",this._t.lgSleep]' in panel
    assert '["accent",this._t.lgAccent]' in panel
    assert '["task",this._t.lgTask]' in panel
    assert "_lights_activation" in panel
    assert "_lights_blocking_states" in panel
    assert "_lights_brightness" in panel
    assert "light_group:${lights}" in panel
    assert "_lights_act_on" not in panel
    assert "_lights_states" not in panel


def test_panel_exposes_final_light_control_labels() -> None:
    """The Light tab keeps user-facing German labels for its current mappings."""
    for label in (
        "Lichtsteuerung",
        "Bereich",
        "Lichtautomatik",
        "Einschalten bei höchstens",
        "Ausschalten bei mindestens",
        "Ausschalten nach Abwesenheit",
        "Sekunden",
        "Zwischen beiden Werten bleibt der aktuelle Zustand erhalten.",
        "Aktueller Status",
        "Lichtgruppen",
        "Deckenleuchten",
        "Schlaflichter",
        "Akzentlichter",
        "Arbeitslichter",
        "Zustand beibehalten",
        "Keine automatische Aktion",
        "Manuell eingeschaltet",
        "Manuell ausgeschaltet",
        "Nicht aktiv",
        "Bei Belegung",
    ):
        assert label in _dashboard_texts()


def test_panel_settings_renderer_is_defined_and_uses_global_websocket_api() -> None:
    """The Settings tab renders and saves through the existing global WebSocket API."""
    panel = Path(
        "custom_components/adaptive_areas/frontend/adaptive-areas-panel.js"
    ).read_text(encoding="utf-8")

    for method in (
        "_renderSettings(t){",
        "_renderGlobalSettings(){",
        "_scopedSingle(key,value,label,domain,scoped){",
        "_isGlobalSettingsDirty(){",
        "async _saveGlobalSettings(){",
    ):
        assert method in panel, f"missing panel method {method}"

    assert 'name="weather_entity"' in panel
    assert 'name="global_light_sensor"' in panel
    assert 'type:"adaptive_areas/get_global_configuration"' in panel
    assert 'type:"adaptive_areas/update_global_configuration"' in panel
    assert "friendly_name" in PICKER_SOURCE.read_text(encoding="utf-8")
    assert "_saveGlobalSettings(){" in panel and "t.saveFailed" in panel


def test_panel_climate_target_shows_friendly_name_with_entity_id_fallback() -> None:
    """The thermostat select shows friendly names and keeps the entity id as fallback."""
    # Live path: the shared entity picker labels with the friendly name, falls back to the
    # entity id, and keeps a stored value that is not in the states (marked, never dropped).
    picker = PICKER_SOURCE.read_text(encoding="utf-8")
    assert "friendly_name" in picker
    assert "this.selected" in picker and "_mark(" in picker


def test_panel_calls_only_defined_methods() -> None:
    """Every `this._method(` call in the panel has a matching method definition."""

    panel = Path(
        "custom_components/adaptive_areas/frontend/adaptive-areas-panel.js"
    ).read_text(encoding="utf-8")

    called = set(re.findall(r"this\.(_\w+)\(", panel))
    defined = set(re.findall(r"(?:async\s+)?(_\w+)\([^)]*\)\{", panel))

    assert sorted(called - defined) == []
