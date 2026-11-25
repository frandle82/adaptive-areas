"""Partial setup failure: the existing rollback releases what was registered; a retry works.

The failure point is the existing platform forward (`async_forward_entry_setups`), which runs after
the entry's listeners are tracked and before the Areas are activated. It is injected with
monkeypatch only; the rollback, the listeners and the retried setup are the production code.
"""

from __future__ import annotations

from homeassistant.const import EVENT_CALL_SERVICE, STATE_OFF, STATE_ON
from homeassistant.helpers import area_registry as ar
from homeassistant.core import HomeAssistant
import pytest

from custom_components.adaptive_areas.const import DATA_AREA_OBJECT, MODULE_DATA
from tests import test_light_coordination_regression as regression
from tests.test_light import setup_entities_light_one  # noqa: F401
from tests.test_light_coordination_regression import (  # noqa: F401
    CALLS,
    LIGHT,
    LUX,
    probe_devices,
)

pytestmark = pytest.mark.usefixtures("probe_devices")

OWN_EVENT_TYPES = (
    "entity_registry_updated",
    "device_registry_updated",
    "floor_registry_updated",
    "label_registry_updated",
    "category_registry_updated",
    "state_changed",
)


def _own_listeners(hass: HomeAssistant) -> dict[str, int]:
    counts = hass.bus.async_listeners()
    return {event: counts.get(event, 0) for event in OWN_EVENT_TYPES}


def _group_on_calls() -> list:
    return [call for call in CALLS if call[0] == "turn_on" and "overhead" in call[1]]


async def test_failed_platform_setup_releases_listeners_and_areas_then_retry_works(
    hass, monkeypatch
) -> None:
    """A failed forward releases the tracked listeners and Areas; the retry reacts exactly once."""
    hass.bus.async_listen(EVENT_CALL_SERVICE, regression._on_call)
    hass.states.async_set(LUX, "50", {"unit_of_measurement": "lx"})
    hass.states.async_set(regression.MOTION, STATE_OFF)
    hass.states.async_set(regression.SLEEP, STATE_OFF)
    if ar.async_get(hass).async_get_area("kitchen") is None:
        ar.async_get(hass).async_create("Kitchen")
    entry = regression._entry()
    entry.add_to_hass(hass)
    await hass.async_block_till_done()
    baseline = _own_listeners(hass)

    real_forward = hass.config_entries.async_forward_entry_setups

    async def failing_forward(*args, **kwargs):
        raise RuntimeError("injected platform failure")

    monkeypatch.setattr(
        hass.config_entries, "async_forward_entry_setups", failing_forward
    )
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert _own_listeners(hass) == baseline
    assert entry.entry_id not in hass.data.get(MODULE_DATA, {})

    monkeypatch.setattr(hass.config_entries, "async_forward_entry_setups", real_forward)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    await regression._enable_group_control(hass)
    CALLS.clear()
    hass.states.async_set(regression.MOTION, STATE_ON)
    await hass.async_block_till_done()
    assert len(_group_on_calls()) == 1
    area = hass.data[MODULE_DATA][entry.entry_id][DATA_AREA_OBJECT]
    assert area is not None
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert _own_listeners(hass) == baseline
