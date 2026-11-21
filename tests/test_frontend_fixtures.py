"""Export realistic WebSocket responses for the frontend browser harness.

Fixtures are produced by the real backend handlers, never written by hand.
They are written only when ADAPTIVE_AREAS_WRITE_FIXTURES=1 is set, so a normal
test run does not modify the working tree.
"""

import json
import os
from pathlib import Path
from types import SimpleNamespace


from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant

from custom_components.adaptive_areas.const import (
    CONF_GLOBAL_ENTRY,
    CONF_GLOBAL_OPTIONS,
    DOMAIN,
)
from custom_components.adaptive_areas.websocket import async_register_websocket_commands

FIXTURE_DIR = Path(__file__).parent / "frontend" / "fixtures"


class _Connection:
    def __init__(self, *, is_admin: bool) -> None:
        self.user = SimpleNamespace(is_admin=is_admin)
        self.result = None

    def send_result(self, _msg_id, result=None) -> None:
        self.result = result

    def send_error(self, _msg_id, code, message) -> None:
        raise AssertionError(f"unexpected error {code}: {message}")

    def send_event(self, _msg_id, event) -> None:  # pragma: no cover
        pass


async def _call(hass: HomeAssistant, connection: _Connection, command: str, **data):
    handler, schema = hass.data["websocket_api"][command]
    message = {"id": 1, "type": command, **data}
    handler(hass, connection, message if schema is False else schema(message))
    await hass.async_block_till_done()
    return connection.result


async def test_export_frontend_fixtures(
    hass: HomeAssistant,
    basic_config_entry,
    entities_binary_sensor_motion_one,
    _setup_integration_basic,
) -> None:
    """Record the backend contract the panel consumes (admin and non-admin)."""
    admin = _Connection(is_admin=True)
    user = _Connection(is_admin=False)
    motion = entities_binary_sensor_motion_one[0].entity_id
    for value in ("on", "off", "on"):
        hass.states.async_set(motion, value)
        await hass.async_block_till_done()
    overview_admin = await _call(hass, admin, "adaptive_areas/get_overview")
    overview_user = await _call(hass, user, "adaptive_areas/get_overview")
    area_id = overview_admin["areas"][0]["id"]
    fixtures = {
        "get_overview.admin.json": overview_admin,
        "get_overview.user.json": overview_user,
        "get_area.admin.json": await _call(
            hass, admin, "adaptive_areas/get_area", area_id=area_id
        ),
        "get_area.user.json": await _call(
            hass, user, "adaptive_areas/get_area", area_id=area_id
        ),
        "get_area_configuration.admin.json": await _call(
            hass, admin, "adaptive_areas/get_area_configuration"
        ),
        "get_light_runtime_status.admin.json": await _call(
            hass, admin, "adaptive_areas/get_light_runtime_status", area_id=area_id
        ),
        "get_climate_runtime_status.admin.json": await _call(
            hass, admin, "adaptive_areas/get_climate_runtime_status", area_id=area_id
        ),
        "get_decision_trace.admin.json": await _call(
            hass, admin, "adaptive_areas/get_decision_trace", area_id=area_id, limit=20
        ),
        "get_diagnostics.admin.json": await _call(
            hass, admin, "adaptive_areas/get_diagnostics"
        ),
    }
    if os.environ.get("ADAPTIVE_AREAS_WRITE_FIXTURES") == "1":
        FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
        for name, payload in fixtures.items():
            (FIXTURE_DIR / name).write_text(
                json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
                + "\n",
                encoding="utf-8",
            )
    for name, payload in fixtures.items():
        assert payload is not None, name
        json.dumps(payload)


async def test_export_global_configuration_fixture(hass: HomeAssistant) -> None:
    """Record the global options contract from a real GlobalEntry only.

    Kept separate: the basic area entry is not a GlobalEntry, and the global
    command requires exactly one.
    """
    hass.states.async_set("weather.home", "sunny", {"friendly_name": "Home"})
    hass.states.async_set(
        "sensor.outdoor_lux",
        "250",
        {"device_class": "illuminance", "unit_of_measurement": "lx"},
    )
    global_entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_GLOBAL_ENTRY: True},
        options={
            CONF_GLOBAL_OPTIONS: {
                "weather_entity": "weather.home",
                "global_light_sensor": "sensor.outdoor_lux",
            }
        },
    )
    global_entry.add_to_hass(hass)
    async_register_websocket_commands(hass)
    payload = await _call(
        hass, _Connection(is_admin=True), "adaptive_areas/get_global_configuration"
    )
    assert payload["ok"] is True
    if os.environ.get("ADAPTIVE_AREAS_WRITE_FIXTURES") == "1":
        FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
        (FIXTURE_DIR / "get_global_configuration.admin.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )


async def test_export_multi_area_overview_fixtures(
    hass: HomeAssistant,
    all_areas_with_meta_config_entry,
    entities_binary_sensor_motion_all_areas_with_meta,
    _setup_integration_all_areas_with_meta,
) -> None:
    """Record a multi-area overview with Meta-Areas from the real handlers.

    Synthetic test data only: the areas and sensors come from the test
    configuration in conftest.py, nothing is taken from a live instance.
    """
    for sensors in entities_binary_sensor_motion_all_areas_with_meta.values():
        for sensor in sensors:
            hass.states.async_set(sensor.entity_id, "on")
    await hass.async_block_till_done()
    admin = _Connection(is_admin=True)
    user = _Connection(is_admin=False)
    fixtures = {
        "get_overview.multi.admin.json": await _call(
            hass, admin, "adaptive_areas/get_overview"
        ),
        "get_overview.multi.user.json": await _call(
            hass, user, "adaptive_areas/get_overview"
        ),
    }
    if os.environ.get("ADAPTIVE_AREAS_WRITE_FIXTURES") == "1":
        FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
        for name, payload in fixtures.items():
            (FIXTURE_DIR / name).write_text(
                json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
                + "\n",
                encoding="utf-8",
            )
    for name, payload in fixtures.items():
        assert payload is not None, name
        json.dumps(payload)


async def test_export_presence_state_overview_fixtures(
    hass: HomeAssistant,
    all_areas_with_meta_config_entry,
    entities_binary_sensor_motion_all_areas_with_meta,
    _setup_integration_all_areas_with_meta,
) -> None:
    """Record presence states from the real handlers: occupied, clear, unavailable, unknown.

    The motion sensors of the test configuration get different states, so the
    overview contains each presence case the backend can report. Nothing is
    invented: values are only set on the test entities.
    """
    admin = _Connection(is_admin=True)
    user = _Connection(is_admin=False)
    sensors = []
    for group in entities_binary_sensor_motion_all_areas_with_meta.values():
        sensors.extend(group)
    cases = ["on", "off", "unavailable", None]
    for index, sensor in enumerate(sorted(sensors, key=lambda item: item.entity_id)):
        state = cases[index % len(cases)]
        if state is None:
            hass.states.async_remove(sensor.entity_id)
        else:
            hass.states.async_set(sensor.entity_id, state)
    await hass.async_block_till_done()
    fixtures = {
        "get_overview.presence.admin.json": await _call(
            hass, admin, "adaptive_areas/get_overview"
        ),
        "get_overview.presence.user.json": await _call(
            hass, user, "adaptive_areas/get_overview"
        ),
    }
    if os.environ.get("ADAPTIVE_AREAS_WRITE_FIXTURES") == "1":
        FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
        for name, payload in fixtures.items():
            (FIXTURE_DIR / name).write_text(
                json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
                + "\n",
                encoding="utf-8",
            )
    for name, payload in fixtures.items():
        assert payload is not None, name
        json.dumps(payload)


async def test_export_acceptance_overview_fixtures(
    hass: HomeAssistant,
    all_areas_with_meta_config_entry,
    entities_binary_sensor_motion_all_areas_with_meta,
    _setup_integration_all_areas_with_meta,
) -> None:
    """Shared V06 acceptance fixture: floors, Meta-Areas and all presence states.

    Built from the real handlers. Presence states are set on the test motion
    sensors only: on, off, unavailable, and no state (unknown).
    """
    cases = ["on", "off", "unavailable", None]
    sensors = []
    for group in entities_binary_sensor_motion_all_areas_with_meta.values():
        sensors.extend(group)
    for index, sensor in enumerate(sorted(sensors, key=lambda item: item.entity_id)):
        state = cases[index % len(cases)]
        if state is None:
            hass.states.async_remove(sensor.entity_id)
        else:
            hass.states.async_set(sensor.entity_id, state)
    await hass.async_block_till_done()
    admin = _Connection(is_admin=True)
    user = _Connection(is_admin=False)
    fixtures = {
        "get_overview.acceptance.admin.json": await _call(
            hass, admin, "adaptive_areas/get_overview"
        ),
        "get_overview.acceptance.user.json": await _call(
            hass, user, "adaptive_areas/get_overview"
        ),
    }
    if os.environ.get("ADAPTIVE_AREAS_WRITE_FIXTURES") == "1":
        FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
        for name, payload in fixtures.items():
            (FIXTURE_DIR / name).write_text(
                json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
                + "\n",
                encoding="utf-8",
            )
    for name, payload in fixtures.items():
        assert payload is not None, name
        json.dumps(payload)


async def test_export_acceptance_diagnostics_fixtures(
    hass: HomeAssistant,
    all_areas_with_meta_config_entry,
    entities_binary_sensor_motion_all_areas_with_meta,
    _setup_integration_all_areas_with_meta,
) -> None:
    """Diagnostics from the real handler for the shared acceptance states.

    The same presence states as the acceptance overview are used: unavailable
    and missing sources produce the real technical issues and unknown-source
    entries of the backend.
    """
    cases = ["on", "off", "unavailable", None]
    sensors = []
    for group in entities_binary_sensor_motion_all_areas_with_meta.values():
        sensors.extend(group)
    for index, sensor in enumerate(sorted(sensors, key=lambda item: item.entity_id)):
        state = cases[index % len(cases)]
        if state is None:
            hass.states.async_remove(sensor.entity_id)
        else:
            hass.states.async_set(sensor.entity_id, state)
    await hass.async_block_till_done()
    fixtures = {
        "get_diagnostics.acceptance.admin.json": await _call(
            hass, _Connection(is_admin=True), "adaptive_areas/get_diagnostics"
        ),
    }
    if os.environ.get("ADAPTIVE_AREAS_WRITE_FIXTURES") == "1":
        FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
        for name, payload in fixtures.items():
            (FIXTURE_DIR / name).write_text(
                json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
                + "\n",
                encoding="utf-8",
            )
    for name, payload in fixtures.items():
        assert payload is not None, name
        json.dumps(payload)


async def test_export_empty_trace_fixture(
    hass: HomeAssistant, basic_config_entry, _setup_integration_basic
) -> None:
    """Empty decision trace from the real handler (boundary case for the trace view)."""
    admin = _Connection(is_admin=True)
    area_id = (await _call(hass, admin, "adaptive_areas/get_overview"))["areas"][0][
        "id"
    ]
    payload = await _call(
        hass, admin, "adaptive_areas/get_decision_trace", area_id=area_id, limit=20
    )
    assert payload is not None and payload["entries"] == []
    if os.environ.get("ADAPTIVE_AREAS_WRITE_FIXTURES") == "1":
        FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
        (FIXTURE_DIR / "get_decision_trace.empty.admin.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    json.dumps(payload)
