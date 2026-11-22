"""Native diagnostics: presence evaluation per Area (read-only, privacy-preserving)."""

from __future__ import annotations

import json

from homeassistant.core import HomeAssistant

from custom_components.adaptive_areas.const import (
    CONF_EXCLUDE_ENTITIES,
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
    _isolate,
)
from tests.test_dashboard_presence_state import _area

pytest_plugins = ["tests.test_dashboard_presence_state"]

GATE = "binary_sensor.probe_gate"
SECOND = "binary_sensor.probe_second"


def _entry(hass: HomeAssistant):
    return _area(hass, AREA).hass_config


async def _evaluation(hass: HomeAssistant) -> dict:
    diagnostics = await async_get_config_entry_diagnostics(hass, _entry(hass))
    return diagnostics["presence"]["evaluation"]


def _by_domain_device(sources: list[dict], origin: str) -> list[dict]:
    return [source for source in sources if source["origin"] == origin]


async def test_inactive_evaluable_source(hass, multi_area) -> None:
    """Available source with state off: evaluated, not active."""
    _isolate(hass, AREA, multi_area[AREA])
    hass.states.async_set(PROBE, "off")
    await _apply(hass, AREA, **{CONF_INCLUDE_ENTITIES: [PROBE]})
    evaluation = await _evaluation(hass)
    source = next(s for s in evaluation["sources"] if s["origin"] == "manual")
    assert source["status"] == "available"
    assert source["evaluated"] is True
    assert source["raw_active"] is False
    assert evaluation["reason"] == "evaluable_source_inactive"


async def test_active_source_is_raw_active(hass, multi_area) -> None:
    """Available source with state on: raw signal active, reason from the confirmed state."""
    _isolate(hass, AREA, multi_area[AREA])
    hass.states.async_set(PROBE, "on")
    await _apply(hass, AREA, **{CONF_INCLUDE_ENTITIES: [PROBE]})
    evaluation = await _evaluation(hass)
    assert evaluation["raw_signal_active"] is True
    assert evaluation["confirmed_occupied"] is True
    assert evaluation["reason"] == "confirmed_occupied"


async def test_unavailable_source_is_not_evaluated(hass, multi_area) -> None:
    """Unavailable source: status unavailable, not evaluated, reason unknown."""
    _isolate(hass, AREA, multi_area[AREA])
    hass.states.async_set(PROBE, "unavailable")
    await _apply(hass, AREA, **{CONF_INCLUDE_ENTITIES: [PROBE]})
    evaluation = await _evaluation(hass)
    source = next(s for s in evaluation["sources"] if s["origin"] == "manual")
    assert source["status"] == "unavailable"
    assert source["evaluated"] is False
    assert evaluation["reason"] == "no_evaluable_source"


async def test_manual_source_without_device_class_is_listed(hass, multi_area) -> None:
    """Manual include without device class: origin manual, device class None."""
    _isolate(hass, AREA, multi_area[AREA])
    hass.states.async_set(PROBE, "off")
    await _apply(hass, AREA, **{CONF_INCLUDE_ENTITIES: [PROBE]})
    evaluation = await _evaluation(hass)
    manual = _by_domain_device(evaluation["sources"], "manual")
    assert len(manual) == 1
    assert manual[0]["device_class"] is None
    assert manual[0]["domain"] == "binary_sensor"
    assert evaluation["manual_include_count"] == 1


async def test_exclude_wins_over_include(hass, multi_area) -> None:
    """Excluded and included entity is not listed as a source."""
    _isolate(hass, AREA, multi_area[AREA])
    hass.states.async_set(PROBE, "on")
    await _apply(
        hass,
        AREA,
        **{CONF_INCLUDE_ENTITIES: [PROBE], CONF_EXCLUDE_ENTITIES: [PROBE]},
    )
    evaluation = await _evaluation(hass)
    assert all(s["origin"] != "manual" for s in evaluation["sources"])
    assert evaluation["exclude_count"] == 1
    assert evaluation["raw_signal_active"] is False


async def test_mixed_sources_are_reported_individually(hass, multi_area) -> None:
    """Several sources with different states keep their own status."""
    _isolate(hass, AREA, multi_area[AREA])
    hass.states.async_set(PROBE, "on")
    hass.states.async_set(SECOND, "unavailable")
    await _apply(hass, AREA, **{CONF_INCLUDE_ENTITIES: [PROBE, SECOND]})
    evaluation = await _evaluation(hass)
    statuses = sorted(
        (s["origin"], s["status"], s["raw_active"]) for s in evaluation["sources"]
    )
    assert ("manual", "available", True) in statuses
    assert ("manual", "unavailable", False) in statuses
    assert evaluation["raw_signal_active"] is True


async def test_missing_entity_is_not_listed_and_does_not_fail(hass, multi_area) -> None:
    """A configured ID without state or registry entry is skipped, not invented."""
    _isolate(hass, AREA, multi_area[AREA])
    await _apply(
        hass, AREA, **{CONF_INCLUDE_ENTITIES: ["binary_sensor.does_not_exist"]}
    )
    evaluation = await _evaluation(hass)
    assert all(s["origin"] != "manual" for s in evaluation["sources"])


async def test_gate_closed_and_open_are_reported(hass, multi_area) -> None:
    """Gate state is reported separately from the raw signal."""
    _isolate(hass, AREA, multi_area[AREA])
    hass.states.async_set(GATE, "off")
    hass.states.async_set(PROBE, "on")
    await _apply(
        hass,
        AREA,
        **{CONF_INCLUDE_ENTITIES: [PROBE], CONF_PRESENCE_CONTROL_ENTITIES: [GATE]},
    )
    closed = await _evaluation(hass)
    assert closed["gate_open"] is False
    assert closed["presence_control"][0]["open"] is False

    hass.states.async_set(GATE, "on")
    await hass.async_block_till_done()
    opened = await _evaluation(hass)
    assert opened["gate_open"] is True
    assert opened["presence_control"][0]["status"] == "available"


async def test_output_contains_no_entity_ids_and_config_is_unchanged(
    hass, multi_area
) -> None:
    """Privacy: no entity IDs in the export; the export does not change the config."""
    _isolate(hass, AREA, multi_area[AREA])
    hass.states.async_set(PROBE, "on")
    await _apply(hass, AREA, **{CONF_INCLUDE_ENTITIES: [PROBE]})
    entry = _entry(hass)
    options_before = json.dumps(dict(entry.options), sort_keys=True, default=str)
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    evaluation = diagnostics["presence"]["evaluation"]
    serialized = json.dumps(evaluation)
    assert PROBE not in serialized
    assert "motion_sensor_front_yard" not in serialized
    assert (
        json.dumps(dict(entry.options), sort_keys=True, default=str) == options_before
    )
