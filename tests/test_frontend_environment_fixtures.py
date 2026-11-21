"""Environment fixtures and regressions for the dashboard, from the real handlers.

The Area's environment feature is enabled with registered sensors. The
Environment Engine is evaluated through Home Assistant's time mechanism
(`async_fire_time_changed`), because state changes are debounced by 0.5 s in
helpers/environment.py. Only the test sensors are set; nothing is invented.
"""

from __future__ import annotations

from datetime import timedelta
import json
import os
from pathlib import Path
from types import SimpleNamespace

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from homeassistant.util import dt as dt_util

from custom_components.adaptive_areas.const import (
    CONF_AREA_HUMIDITY_SENSOR,
    CONF_AREA_TEMPERATURE_SENSOR,
    CONF_ENABLED_FEATURES,
    CONF_FEATURE_ENVIRONMENT,
    CONF_INCLUDE_ENTITIES,
    DOMAIN,
)
from custom_components.adaptive_areas.websocket import async_register_websocket_commands
from tests.const import MockAreaIds
from tests.helpers import get_basic_config_entry_data, init_integration

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


def _register_sensor(hass: HomeAssistant, object_id: str, device_class: str, unit: str):
    """Register a sensor in the entity registry so it belongs to the Area."""
    registry = async_get_entity_registry(hass)
    return registry.async_get_or_create(
        "sensor",
        "adaptive_areas_test",
        object_id,
        suggested_object_id=object_id,
        original_device_class=device_class,
    )


async def _kitchen_with_environment(
    hass: HomeAssistant,
    *,
    temperature: str | None,
    humidity: str | None,
    environment: bool = True,
) -> dict:
    """Set up one physical Area with the environment feature and return its overview entry."""
    async_register_websocket_commands(hass)
    sensors: dict[str, str] = {}
    if temperature is not None:
        entry = _register_sensor(hass, "env_kitchen_temperature", "temperature", "°C")
        hass.states.async_set(
            entry.entity_id,
            temperature,
            {"device_class": "temperature", "unit_of_measurement": "°C"},
        )
        sensors[CONF_AREA_TEMPERATURE_SENSOR] = entry.entity_id
    if humidity is not None:
        entry = _register_sensor(hass, "env_kitchen_humidity", "humidity", "%")
        hass.states.async_set(
            entry.entity_id,
            humidity,
            {"device_class": "humidity", "unit_of_measurement": "%"},
        )
        sensors[CONF_AREA_HUMIDITY_SENSOR] = entry.entity_id

    data = get_basic_config_entry_data(MockAreaIds.KITCHEN)
    data[CONF_ENABLED_FEATURES] = {CONF_FEATURE_ENVIRONMENT: {}} if environment else {}
    data.update(sensors)
    data[CONF_INCLUDE_ENTITIES] = sorted(sensors.values())
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    await init_integration(hass, [entry], areas=[MockAreaIds.KITCHEN])
    await hass.async_block_till_done()
    # Debounced evaluation (helpers/environment.py, _schedule_evaluation): advance the clock.
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=2))
    await hass.async_block_till_done()
    overview = await _call(
        hass, _Connection(is_admin=True), "adaptive_areas/get_overview"
    )
    return next(area for area in overview["areas"] if area["id"] == "kitchen")


async def test_unavailable_humidity_is_reported_as_missing(hass: HomeAssistant) -> None:
    """A registered humidity sensor that is unavailable is reported as missing data."""
    area = await _kitchen_with_environment(
        hass, temperature="21.5", humidity="unavailable"
    )
    environment = area["environment"]
    assert environment is not None
    assert environment["status"] == "available"
    assert "Humidity data missing" in environment["notices"]


async def test_valid_environment_without_notices_reaches_dashboard(
    hass: HomeAssistant,
) -> None:
    """Regression: complete valid measurements must reach the dashboard."""
    area = await _kitchen_with_environment(hass, temperature="21.5", humidity="48")
    assert area["environment"] is not None
    assert area["environment"]["comfort"] == "comfortable"
    assert area["environment"]["humidity"] == "normal"


async def test_export_environment_partial_fixtures(hass: HomeAssistant) -> None:
    """Export the partial-data case (humidity unavailable) for admin and non-admin."""
    async_register_websocket_commands(hass)
    await _kitchen_with_environment(hass, temperature="21.5", humidity="unavailable")
    admin = _Connection(is_admin=True)
    user = _Connection(is_admin=False)
    fixtures = {
        "get_overview.environment_partial.admin.json": await _call(
            hass, admin, "adaptive_areas/get_overview"
        ),
        "get_overview.environment_partial.user.json": await _call(
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


async def _export(hass: HomeAssistant, names: dict[str, _Connection]) -> None:
    """Write the overview for each connection to the named fixture file."""
    async_register_websocket_commands(hass)
    fixtures = {
        name: await _call(hass, connection, "adaptive_areas/get_overview")
        for name, connection in names.items()
    }
    if os.environ.get("ADAPTIVE_AREAS_WRITE_FIXTURES") == "1":
        FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
        for name, payload in fixtures.items():
            (FIXTURE_DIR / name).write_text(
                json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
                + "\n",
                encoding="utf-8",
            )
    for payload in fixtures.values():
        json.dumps(payload)


async def test_valid_environment_is_reported_and_exported(hass: HomeAssistant) -> None:
    """Complete valid measurements: values reach the dashboard for admin and non-admin."""
    area = await _kitchen_with_environment(hass, temperature="21.5", humidity="48")
    assert area["environment"] is not None
    assert area["environment"]["comfort"] == "comfortable"
    assert area["environment"]["humidity"] == "normal"
    assert "notices" not in area["environment"]
    await _export(
        hass,
        {
            "get_overview.environment_valid.admin.json": _Connection(is_admin=True),
            "get_overview.environment_valid.user.json": _Connection(is_admin=False),
        },
    )


async def test_disabled_environment_is_absent(hass: HomeAssistant) -> None:
    """Disabled feature: no environment entry, no values and no notices invented."""
    area = await _kitchen_with_environment(
        hass, temperature="21.5", humidity="48", environment=False
    )
    assert area["environment"] is None
    assert "environment" not in area["enabled_features"]
    await _export(
        hass,
        {
            "get_overview.environment_disabled.admin.json": _Connection(is_admin=True),
            "get_overview.environment_disabled.user.json": _Connection(is_admin=False),
        },
    )
