"""Negative access tests: every administrative WebSocket command rejects non-administrators.

The check calls the real handler (the `require_admin` decorator runs first), so a
removed decorator fails here. Non-admin commands are asserted as readable.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import Unauthorized

from custom_components.adaptive_areas.websocket import async_register_websocket_commands

ADMIN_ONLY = [
    "adaptive_areas/get_decision_trace",
    "adaptive_areas/get_diagnostics",
    "adaptive_areas/get_area_configuration",
    "adaptive_areas/get_light_runtime_status",
    "adaptive_areas/get_climate_runtime_status",
    "adaptive_areas/get_global_configuration",
    "adaptive_areas/update_global_configuration",
    "adaptive_areas/create_area",
    "adaptive_areas/update_area",
    "adaptive_areas/delete_area",
]
READABLE_FOR_NON_ADMIN = [
    "adaptive_areas/get_overview",
    "adaptive_areas/get_area",
]


class _Capture:
    """Connection double that records the outcome instead of raising."""

    def __init__(self, *, is_admin: bool) -> None:
        self.user = SimpleNamespace(is_admin=is_admin)
        self.errors: list[tuple] = []
        self.results: list = []

    def send_result(self, msg_id, result=None) -> None:
        self.results.append(result)

    def send_error(self, msg_id, code, message) -> None:
        self.errors.append((code, message))

    def send_event(self, msg_id, event) -> None:  # pragma: no cover
        pass


@pytest.fixture
async def commands(hass: HomeAssistant, basic_config_entry, _setup_integration_basic):
    """Register the WebSocket commands and return the handler table."""
    async_register_websocket_commands(hass)
    return hass.data["websocket_api"]


@pytest.mark.parametrize("command", ADMIN_ONLY)
async def test_non_admin_is_rejected(hass: HomeAssistant, commands, command) -> None:
    """A non-admin never gets a result from an administrative command."""
    handler, _schema = commands[command]
    connection = _Capture(is_admin=False)
    with pytest.raises(Unauthorized):
        handler(
            hass,
            connection,
            {"id": 1, "type": command, "area_id": "kitchen", "options": {}},
        )
    await hass.async_block_till_done()
    assert connection.results == [], command


@pytest.mark.parametrize("command", READABLE_FOR_NON_ADMIN)
async def test_non_admin_commands_stay_readable(
    hass: HomeAssistant, commands, command
) -> None:
    """Commands intended for every user are not blocked by the admin check."""
    handler, _schema = commands[command]
    connection = _Capture(is_admin=False)
    handler(hass, connection, {"id": 1, "type": command, "area_id": "kitchen"})
    await hass.async_block_till_done()
    assert connection.errors == [], command
