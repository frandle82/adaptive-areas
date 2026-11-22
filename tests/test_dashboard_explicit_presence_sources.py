"""Dashboard presence status for explicitly included presence sources (Schritt 1).

A manually included entity counts as a presence source even without an allowed
device class. Exclusions still win. Automatically discovered entities keep the
device-class filter. Only evaluable sources decide between `clear` and `unknown`.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
import pytest

from custom_components.adaptive_areas.const import (
    CONF_EXCLUDE_ENTITIES,
    CONF_INCLUDE_ENTITIES,
)
from tests.test_dashboard_presence_state import _area, _by_id, _overview

pytest_plugins = ["tests.test_dashboard_presence_state"]

AREA = "front_yard"
PROBE = "binary_sensor.probe_manual_source"


def _isolate(hass: HomeAssistant, area_id: str, sensors: list[str]) -> None:
    """Make every registered source of the Area unavailable."""
    for entity_id in sensors:
        hass.states.async_set(entity_id, "unavailable")


async def _presence(hass: HomeAssistant, area_id: str = AREA) -> dict:
    areas = _by_id(await _overview(hass))
    return areas[area_id]["presence"]


@pytest.fixture
def probe_area(hass: HomeAssistant, multi_area) -> None:
    """Disable the registered sources of the Area under test."""
    _isolate(hass, AREA, multi_area[AREA])


async def _apply(hass: HomeAssistant, area_id: str, **options) -> None:
    """Store Area options and reload, as the real options flow does."""
    entry = _area(hass, area_id).hass_config
    hass.config_entries.async_update_entry(entry, options={**entry.options, **options})
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()


async def test_included_source_without_device_class_is_evaluated(
    hass, probe_area
) -> None:
    """Explicit include bypasses the device-class filter: off -> clear."""
    hass.states.async_set(PROBE, "off")
    await _apply(hass, AREA, **{CONF_INCLUDE_ENTITIES: [PROBE]})
    presence = await _presence(hass)
    assert presence["state"] == "clear"
    assert presence["available"] == 1


async def test_included_source_on_is_occupied(hass, probe_area) -> None:
    """An included source that is on makes the Area occupied."""
    hass.states.async_set(PROBE, "off")
    await _apply(hass, AREA, **{CONF_INCLUDE_ENTITIES: [PROBE]})
    hass.states.async_set(PROBE, "on")
    await hass.async_block_till_done()
    assert (await _presence(hass))["state"] == "occupied"


async def test_included_unknown_and_unavailable_are_not_evaluable(
    hass, probe_area
) -> None:
    """Unknown and unavailable never count as evaluable."""
    hass.states.async_set(PROBE, "off")
    await _apply(hass, AREA, **{CONF_INCLUDE_ENTITIES: [PROBE]})
    for state in ("unknown", "unavailable"):
        hass.states.async_set(PROBE, state)
        await hass.async_block_till_done()
        presence = await _presence(hass)
        assert presence["state"] == "unknown"
        assert presence["available"] == 0


async def test_excluded_and_included_entity_is_not_a_source(hass, probe_area) -> None:
    """exclude_entities wins over include_entities."""
    hass.states.async_set(PROBE, "off")
    await _apply(
        hass,
        AREA,
        **{CONF_INCLUDE_ENTITIES: [PROBE], CONF_EXCLUDE_ENTITIES: [PROBE]},
    )
    presence = await _presence(hass)
    assert presence["state"] == "unknown"
    assert presence["available"] == 0


async def test_automatic_source_keeps_device_class_filter(hass, probe_area) -> None:
    """Auto-discovered binary sensor without an allowed device class is ignored."""
    hass.states.async_set(PROBE, "off", {"device_class": "door"})
    await hass.async_block_till_done()
    assert (await _presence(hass))["state"] == "unknown"
