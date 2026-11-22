"""Presence control gate semantics for the dashboard and diagnostics.

A closed gate does not confirm occupancy. The dashboard may still show `clear`
when the Area is reliably not occupied. The diagnostics separate the raw source
signal from the confirmed occupancy and give a reason code.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
import pytest

from custom_components.adaptive_areas.const import (
    CONF_INCLUDE_ENTITIES,
    CONF_PRESENCE_CONTROL_ENTITIES,
)
from custom_components.adaptive_areas.diagnostics import (
    async_get_config_entry_diagnostics,
)
from tests.test_dashboard_explicit_presence_sources import (
    AREA,
    PROBE,
    _apply,
    _presence,
    _isolate,
)
from tests.test_dashboard_presence_state import _area

pytest_plugins = ["tests.test_dashboard_presence_state"]

GATE = "binary_sensor.probe_gate"


async def _configure(hass: HomeAssistant, multi_area, gate: str, source: str):
    """Set gate and source states before reload, then apply the configuration."""
    _isolate(hass, AREA, multi_area[AREA])
    hass.states.async_set(GATE, gate)
    hass.states.async_set(PROBE, "off")
    await _apply(
        hass,
        AREA,
        **{CONF_INCLUDE_ENTITIES: [PROBE], CONF_PRESENCE_CONTROL_ENTITIES: [GATE]},
    )
    if source != "off":
        hass.states.async_set(PROBE, source)
    await hass.async_block_till_done()


async def _evaluation(hass: HomeAssistant, entry) -> dict:
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    return diagnostics["presence"]["evaluation"]


def _entry(hass: HomeAssistant):
    return _area(hass, AREA).hass_config


async def test_closed_gate_with_active_source_is_not_confirmed(
    hass, multi_area
) -> None:
    """Gate closed, raw source on: not occupied, raw signal kept visible."""
    await _configure(hass, multi_area, gate="off", source="on")
    presence = await _presence(hass)
    evaluation = await _evaluation(hass, _entry(hass))
    assert presence["state"] == "clear"
    assert evaluation["gate_open"] is False
    assert evaluation["raw_signal_active"] is True
    assert evaluation["confirmed_occupied"] is False
    assert evaluation["reason"] == "raw_signal_not_confirmed"


async def test_open_gate_with_active_source_is_occupied(hass, multi_area) -> None:
    """Gate open, source on: confirmed occupied."""
    await _configure(hass, multi_area, gate="on", source="on")
    presence = await _presence(hass)
    evaluation = await _evaluation(hass, _entry(hass))
    assert presence["state"] == "occupied"
    assert evaluation["gate_open"] is True
    assert evaluation["confirmed_occupied"] is True
    assert evaluation["reason"] == "confirmed_occupied"


async def test_closed_gate_with_inactive_source_is_clear(hass, multi_area) -> None:
    """Gate closed, source off: reliably not occupied, so clear."""
    await _configure(hass, multi_area, gate="off", source="off")
    presence = await _presence(hass)
    evaluation = await _evaluation(hass, _entry(hass))
    assert presence["state"] == "clear"
    assert evaluation["raw_signal_active"] is False
    assert evaluation["reason"] == "evaluable_source_inactive"


@pytest.mark.parametrize("state", ["unavailable", "unknown"])
async def test_only_non_evaluable_sources_are_unknown(hass, multi_area, state) -> None:
    """Only unavailable or unknown sources: unknown, never clear."""
    await _configure(hass, multi_area, gate="on", source=state)
    presence = await _presence(hass)
    evaluation = await _evaluation(hass, _entry(hass))
    assert presence["state"] == "unknown"
    assert evaluation["reason"] == "no_evaluable_source"
    assert evaluation["raw_signal_active"] is False
