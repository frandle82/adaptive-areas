"""Role-aware dashboard DTOs, decision-trace allowlists and WebSocket permissions."""

import json
import re
from types import SimpleNamespace

import pytest
import voluptuous as vol

from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import Unauthorized

from custom_components.adaptive_areas.const import DATA_AREA_OBJECT, MODULE_DATA
from custom_components.adaptive_areas.dashboard import _trace_entry

# Entity identifiers in any Home Assistant domain, e.g. "binary_sensor.kitchen".
ENTITY_ID_PATTERN = re.compile(
    r"\b(binary_sensor|sensor|light|switch|climate|media_player|fan|cover|number|device_tracker)\.[a-z0-9_]+"
)


class _Connection:
    """Minimal WebSocket connection with a configurable user role."""

    def __init__(self, *, is_admin: bool) -> None:
        self.user = SimpleNamespace(is_admin=is_admin)
        self.result = None
        self.errors = []
        self.events = []
        self.subscriptions = {}

    def send_result(self, _msg_id, result=None) -> None:
        self.result = result

    def send_error(self, _msg_id, code, message) -> None:
        self.errors.append((code, message))

    def send_event(self, _msg_id, event) -> None:
        self.events.append(event)


async def _call(
    hass: HomeAssistant, connection: _Connection, command: str, **data
) -> None:
    handler, schema = hass.data["websocket_api"][command]
    message = {"id": 1, "type": command, **data}
    handler(hass, connection, message if schema is False else schema(message))
    await hass.async_block_till_done()


def _area(hass: HomeAssistant, entry):
    return hass.data[MODULE_DATA][entry.entry_id][DATA_AREA_OBJECT]


async def test_non_admin_overview_has_no_entity_identifiers(
    hass: HomeAssistant, basic_config_entry, _setup_integration_basic
) -> None:
    """Non-administrators get aggregated source data and no control entries."""
    connection = _Connection(is_admin=False)
    await _call(hass, connection, "adaptive_areas/get_overview")

    assert connection.result is not None
    assert all("controls" not in area for area in connection.result["areas"])
    assert ENTITY_ID_PATTERN.search(json.dumps(connection.result)) is None


async def test_admin_overview_keeps_control_detail(
    hass: HomeAssistant, basic_config_entry, _setup_integration_basic
) -> None:
    """Administrators keep the existing configuration and runtime detail."""
    connection = _Connection(is_admin=True)
    await _call(hass, connection, "adaptive_areas/get_overview")

    assert any("controls" in area for area in connection.result["areas"])


async def test_non_admin_area_detail_is_aggregated(
    hass: HomeAssistant, basic_config_entry, _setup_integration_basic
) -> None:
    """Area detail for non-administrators reports counts instead of entity lists."""
    area = _area(hass, basic_config_entry)
    connection = _Connection(is_admin=False)
    await _call(hass, connection, "adaptive_areas/get_area", area_id=str(area.id))

    detail = connection.result
    assert "light_groups" not in detail
    assert "controls" not in detail
    assert set(detail["presence"]["sources"]) == {"available", "total"}
    assert set(detail["sources"]) == {"available", "total"}
    assert "dark_source" not in detail["brightness_detail"]
    assert ENTITY_ID_PATTERN.search(json.dumps(detail)) is None


async def test_admin_area_detail_keeps_entity_detail(
    hass: HomeAssistant, basic_config_entry, _setup_integration_basic
) -> None:
    """Administrators still receive the entity-level detail."""
    area = _area(hass, basic_config_entry)
    connection = _Connection(is_admin=True)
    await _call(hass, connection, "adaptive_areas/get_area", area_id=str(area.id))

    assert isinstance(connection.result["presence"]["sources"], list)
    assert "controls" in connection.result


async def test_non_admin_subscription_updates_are_redacted(
    hass: HomeAssistant,
    basic_config_entry,
    entities_binary_sensor_motion_one,
    _setup_integration_basic,
) -> None:
    """Pushed area updates follow the same role rule as the request commands."""
    connection = _Connection(is_admin=False)
    await _call(hass, connection, "adaptive_areas/subscribe_updates")
    motion = entities_binary_sensor_motion_one[0].entity_id
    hass.states.async_set(motion, STATE_ON)
    await hass.async_block_till_done()

    assert connection.events, "a state change must produce an update"
    assert all("controls" not in event["area"] for event in connection.events)
    assert ENTITY_ID_PATTERN.search(json.dumps(connection.events)) is None


async def test_non_admin_cannot_read_decision_trace(
    hass: HomeAssistant, basic_config_entry, _setup_integration_basic
) -> None:
    """The decision trace is administrator-only; other users receive an error."""
    area = _area(hass, basic_config_entry)
    connection = _Connection(is_admin=False)
    with pytest.raises(Unauthorized):
        await _call(
            hass, connection, "adaptive_areas/get_decision_trace", area_id=str(area.id)
        )

    assert connection.result is None


async def test_admin_decision_trace_is_newest_first_and_limited(
    hass: HomeAssistant,
    basic_config_entry,
    entities_binary_sensor_motion_one,
    _setup_integration_basic,
) -> None:
    """Administrators get the newest entries first, limited to the requested count."""
    area = _area(hass, basic_config_entry)
    motion = entities_binary_sensor_motion_one[0].entity_id
    for value in (STATE_ON, STATE_OFF, STATE_ON):
        hass.states.async_set(motion, value)
        await hass.async_block_till_done()

    connection = _Connection(is_admin=True)
    await _call(
        hass,
        connection,
        "adaptive_areas/get_decision_trace",
        area_id=str(area.id),
        limit=2,
    )

    entries = connection.result["entries"]
    assert len(entries) <= 2
    timestamps = [entry["timestamp"] for entry in entries if entry["timestamp"]]
    assert timestamps == sorted(timestamps, reverse=True)
    assert set(entries[0]) == {
        "timestamp",
        "feature",
        "trigger",
        "area_state",
        "decision",
        "outcome",
        "reason_codes",
        "target_count",
        "from",
        "to",
        "exception_class",
        # Light group category of a light_groups entry (None for other features).
        "group",
    }


@pytest.mark.parametrize("limit", [0, 21, "x"])
async def test_decision_trace_limit_is_validated(
    hass: HomeAssistant, basic_config_entry, _setup_integration_basic, limit
) -> None:
    """The limit must be an integer between 1 and 20."""
    area = _area(hass, basic_config_entry)
    connection = _Connection(is_admin=True)
    with pytest.raises(vol.Invalid):
        await _call(
            hass,
            connection,
            "adaptive_areas/get_decision_trace",
            area_id=str(area.id),
            limit=limit,
        )


def test_trace_allowlist_replaces_unknown_and_sensitive_values() -> None:
    """Unexpected or identifying values never reach the public DTO."""
    entry = {
        "timestamp": "not-a-date",
        "feature": "device_tracker.aa_bb_cc",
        "trigger": "AA:BB:CC:DD:EE:FF",
        "area_state": ["occupied", "evil-state"],
        "decision": "turn_on",
        "outcome": "executed",
        "reason_codes": ["ble_presence", "aa:bb:cc:dd:ee:ff"],
        "target_count": -5,
        "from": "not-a-state",
        "to": "occupied",
        "exception_class": "Bad Name!",
    }
    dto = _trace_entry(entry)

    assert dto["timestamp"] is None
    assert dto["feature"] == "other"
    assert dto["trigger"] == "other"
    assert dto["area_state"] == ["occupied"]
    assert dto["decision"] == "turn_on"
    assert dto["reason_codes"] == ["ble_presence"]
    assert dto["target_count"] == 0
    assert dto["from"] is None
    assert dto["to"] == "occupied"
    assert dto["exception_class"] is None
    assert ENTITY_ID_PATTERN.search(json.dumps(dto)) is None
    assert "AA:BB" not in json.dumps(dto)


def test_trace_accepts_valid_exception_name_and_timestamp() -> None:
    """Valid optional values are kept as they are."""
    dto = _trace_entry(
        {"timestamp": "2026-11-20T07:00:00Z", "exception_class": "HomeAssistantError"}
    )
    assert dto["timestamp"] == "2026-11-20T07:00:00Z"
    assert dto["exception_class"] == "HomeAssistantError"


async def test_global_entry_without_areas_lists_no_area_configuration(
    hass: HomeAssistant,
) -> None:
    """A GlobalEntry without Areas returns an empty list instead of failing."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.adaptive_areas.const import CONF_GLOBAL_ENTRY, DOMAIN
    from custom_components.adaptive_areas.area_config import area_configurations

    entry = MockConfigEntry(domain=DOMAIN, data={CONF_GLOBAL_ENTRY: True}, options={})
    entry.add_to_hass(hass)
    assert area_configurations(entry) == []


async def test_warning_details_sum_to_warning_count_and_expose_no_identifiers(
    hass: HomeAssistant, basic_config_entry, _setup_integration_basic
) -> None:
    """warning_details attributes existing warnings; the total stays warning_count."""
    from custom_components.adaptive_areas.dashboard import build_area_summary

    summary = build_area_summary(
        hass, _area(hass, basic_config_entry), include_entities=False
    )
    details = summary["warning_details"]
    assert set(details) == {"aggregates", "secondary_states"}
    assert (
        details["aggregates"] + details["secondary_states"] == summary["warning_count"]
    )
    assert ENTITY_ID_PATTERN.search(json.dumps(details)) is None


async def test_non_admin_lights_summary_has_counts_but_no_group_detail(
    hass: HomeAssistant, basic_config_entry, _setup_integration_basic
) -> None:
    """Non-administrators get light counts only; group names stay administrator detail."""
    from custom_components.adaptive_areas.dashboard import build_area_summary

    area = _area(hass, basic_config_entry)
    user = build_area_summary(hass, area, include_entities=False)
    admin = build_area_summary(hass, area, include_entities=True)
    if user["lights"] is not None:
        assert "groups" not in user["lights"]
        assert set(user["lights"]) == {"on", "total"}
    if admin["lights"] is not None:
        assert "groups" in admin["lights"]


def _publish_environment(hass: HomeAssistant, area) -> None:
    """Give a generated entity of the Area the public environment attributes."""
    entity_id = f"binary_sensor.adaptive_areas_presence_tracking_{area.slug}_area_state"
    state = hass.states.get(entity_id)
    hass.states.async_set(
        entity_id,
        state.state,
        {
            **state.attributes,
            "notices": [],
            "temperature": 21.5,
            "used_sensors": ["sensor.kitchen_temperature"],
        },
    )


async def test_non_admin_environment_has_values_but_no_entity_identifiers(
    hass: HomeAssistant, basic_config_entry, _setup_integration_basic
) -> None:
    """Environment values reach every user; entity fields and used sensors do not."""
    area = _area(hass, basic_config_entry)
    _publish_environment(hass, area)
    await hass.async_block_till_done()

    user = _Connection(is_admin=False)
    await _call(hass, user, "adaptive_areas/get_overview")
    environment = user.result["areas"][0]["environment"]
    assert environment == {"temperature": 21.5, "notices": []}
    assert ENTITY_ID_PATTERN.search(json.dumps(user.result)) is None

    detail = _Connection(is_admin=False)
    await _call(hass, detail, "adaptive_areas/get_area", area_id=str(area.id))
    assert detail.result["environment"] == {"temperature": 21.5, "notices": []}
    assert ENTITY_ID_PATTERN.search(json.dumps(detail.result)) is None

    admin = _Connection(is_admin=True)
    await _call(hass, admin, "adaptive_areas/get_overview")
    admin_environment = admin.result["areas"][0]["environment"]
    assert admin_environment["used_sensors"] == ["sensor.kitchen_temperature"]
    assert admin_environment["entity_id"].startswith("binary_sensor.")


async def test_non_admin_subscription_environment_has_no_entity_identifiers(
    hass: HomeAssistant, basic_config_entry, _setup_integration_basic
) -> None:
    """Pushed summaries follow the same environment redaction."""
    area = _area(hass, basic_config_entry)
    connection = _Connection(is_admin=False)
    await _call(hass, connection, "adaptive_areas/subscribe_updates")
    _publish_environment(hass, area)
    await hass.async_block_till_done()

    assert connection.events, "the environment change must produce an update"
    assert ENTITY_ID_PATTERN.search(json.dumps(connection.events)) is None


async def test_overview_exposes_floor_and_meta_members_without_entity_ids(
    hass: HomeAssistant, _setup_integration_all_areas_with_meta
) -> None:
    """Floor metadata and Meta-Area members are IDs and names, never entity IDs."""
    user = _Connection(is_admin=False)
    await _call(hass, user, "adaptive_areas/get_overview")
    areas = user.result["areas"]
    physical = [area for area in areas if area["type"] != "meta"]
    meta = [area for area in areas if area["type"] == "meta"]

    assert physical and meta, "fixture must contain physical and Meta-Areas"
    for area in areas:
        assert "floor_id" in area and "floor_name" in area
    for area in physical:
        assert "members" not in area
    known_ids = {area["id"] for area in physical}
    for area in meta:
        assert isinstance(area["members_total"], int)
        assert isinstance(area["members"], list)
        assert len(area["members"]) <= area["members_total"]
        assert (
            set(area["members"]) <= known_ids
        ), "members must be loaded physical Areas"
    assert ENTITY_ID_PATTERN.search(json.dumps(user.result)) is None


async def test_overview_floor_is_null_without_floor_registry_entry(
    hass: HomeAssistant, basic_config_entry, _setup_integration_basic
) -> None:
    """An Area without a floor reports null, not an invented floor name."""
    area = _area(hass, basic_config_entry)
    area.floor_id = None
    connection = _Connection(is_admin=True)
    await _call(hass, connection, "adaptive_areas/get_overview")
    entry = next(
        item for item in connection.result["areas"] if item["id"] == str(area.id)
    )
    assert entry["floor_id"] is None
    assert entry["floor_name"] is None


async def test_diagnostics_separate_unknown_unavailable_and_incomplete_data(
    hass: HomeAssistant,
    basic_config_entry,
    entities_binary_sensor_motion_one,
    _setup_integration_basic,
) -> None:
    """Unknown sources are informational and make the data incomplete; unavailable ones are warnings."""
    from custom_components.adaptive_areas.dashboard import build_diagnostics

    motion = entities_binary_sensor_motion_one[0].entity_id
    hass.states.async_set(motion, "unknown")
    await hass.async_block_till_done()
    diagnostics = build_diagnostics(hass, "test")
    assert diagnostics["unknown_source_count"] >= 1
    assert diagnostics["data_complete"] is False
    assert diagnostics["unavailable_source_count"] == 0
    assert {issue["code"] for issue in diagnostics["issues"]} == {"unknown_source"}
    assert all(issue["severity"] == "info" for issue in diagnostics["issues"])
    assert diagnostics["warning_count"] == 0

    hass.states.async_set(motion, "unavailable")
    await hass.async_block_till_done()
    diagnostics = build_diagnostics(hass, "test")
    assert diagnostics["unknown_source_count"] == 0
    assert diagnostics["data_complete"] is True
    assert diagnostics["unavailable_source_count"] >= 1
    assert "unavailable_source" in {issue["code"] for issue in diagnostics["issues"]}
    assert diagnostics["warning_count"] == len(
        [issue for issue in diagnostics["issues"] if issue["severity"] == "warning"]
    )


async def test_source_status_distinguishes_missing_unavailable_unknown(
    hass: HomeAssistant, entities_binary_sensor_motion_one
) -> None:
    """The source DTO names each state instead of collapsing them into one flag."""
    from custom_components.adaptive_areas.dashboard import _state_data

    motion = entities_binary_sensor_motion_one[0].entity_id
    assert _state_data(None, "binary_sensor.gone")["status"] == "missing"
    hass.states.async_set(motion, "unavailable")
    assert _state_data(hass.states.get(motion), motion)["status"] == "unavailable"
    hass.states.async_set(motion, "unknown")
    assert _state_data(hass.states.get(motion), motion)["status"] == "unknown"
    hass.states.async_set(motion, "on")
    assert _state_data(hass.states.get(motion), motion)["status"] == "available"
