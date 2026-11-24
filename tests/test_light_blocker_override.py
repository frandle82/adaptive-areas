"""Blocker and manual override on the overhead group (real Home Assistant, real service events).

Product rule: an effective blocker ends a manual override (no existing option keeps it). A
blocker never sends an ON. A dropped OFF is not replayed when the blocker ends. The
automatic calls are counted on the overhead group entity with an automation context.
"""

from __future__ import annotations

import pytest
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.components.light import DATA_COMPONENT
from homeassistant.core import HomeAssistant

from custom_components.adaptive_areas.const import AreaStates, LightGroupCategory
from custom_components.adaptive_areas.light import AreaLightGroup
from tests.test_light import setup_entities_light_one  # noqa: F401
from tests.test_light_clear_cutover import _run
from tests.test_light_coordination_regression import (  # noqa: F401
    SLEEP,
    _dark,
    _entry,
    _free,
    _occupy,
    probe_devices,
)

pytestmark = pytest.mark.usefixtures("probe_devices")

OVERHEAD = "light.adaptive_areas_light_groups_kitchen_overhead_lights"
SEEN: list[dict] = []


def _group(hass: HomeAssistant) -> AreaLightGroup:
    component = hass.data[DATA_COMPONENT]
    for entity in component.entities:
        if isinstance(entity, AreaLightGroup) and str(entity.category) == str(
            LightGroupCategory.OVERHEAD
        ):
            return entity
    raise AssertionError("no runtime overhead group")


def _auto(events: list[dict], service: str) -> list[dict]:
    return [
        e
        for e in events
        if e["service"] == service and e["target"] == OVERHEAD and not e["user"]
    ]


async def _force_override(hass: HomeAssistant) -> None:
    """Precondition: a confirmed manual override, set through the production setter."""
    _group(hass)._set_manual_override(True)
    await hass.async_block_till_done()


async def _sleep_on(hass: HomeAssistant) -> None:
    hass.states.async_set(SLEEP, STATE_ON)
    await hass.async_block_till_done()


async def _sleep_off(hass: HomeAssistant) -> None:
    hass.states.async_set(SLEEP, STATE_OFF)
    await hass.async_block_till_done()


async def _record_override(hass: HomeAssistant) -> None:
    SEEN.append({"override": _group(hass).manual_override})


async def _sleep_on_twice(hass: HomeAssistant) -> None:
    await _sleep_on(hass)
    hass.states.async_set(SLEEP, STATE_ON)  # unchanged state: no new event
    await hass.async_block_till_done()


def _entry_with_sleep_blocker():
    return _entry(blocking=[AreaStates.SLEEP])


async def test_blocker_clears_an_override_without_configured_retention(hass) -> None:
    """Blocker active, no retention configured: the manual override is removed."""
    SEEN.clear()
    await _run(
        hass,
        _entry_with_sleep_blocker(),
        [
            _dark,
            _occupy,
            _force_override,
            _record_override,
            _sleep_on,
            _record_override,
        ],
    )
    assert SEEN == [{"override": True}, {"override": False}]


async def test_blocker_sends_no_automatic_on(hass) -> None:
    """Blocker activation sends no automatic ON; the only automatic call is an OFF."""
    per_step = await _run(
        hass,
        _entry_with_sleep_blocker(),
        [_dark, _occupy, _force_override, _sleep_on],
    )
    assert _auto(per_step[3], "turn_on") == []
    assert len(_auto(per_step[3], "turn_off")) == 1


async def test_blocker_end_does_not_restore_the_cleared_override(hass) -> None:
    """After the blocker ends the cleared override stays cleared."""
    SEEN.clear()
    await _run(
        hass,
        _entry_with_sleep_blocker(),
        [
            _dark,
            _occupy,
            _force_override,
            _sleep_on,
            _sleep_off,
            _record_override,
        ],
    )
    assert SEEN == [{"override": False}]


async def test_repeated_blocker_event_adds_no_automatic_action(hass) -> None:
    """A repeated blocker signal without a state change adds no automatic command."""
    per_step = await _run(
        hass,
        _entry_with_sleep_blocker(),
        [_dark, _occupy, _force_override, _sleep_on, _sleep_on_twice],
    )
    assert _auto(per_step[4], "turn_off") == []
    assert _auto(per_step[4], "turn_on") == []


async def test_clear_during_active_blocker_clears_override_once(hass) -> None:
    """CLEAR while the blocker is active: the override is removed, no duplicate action."""
    SEEN.clear()
    per_step = await _run(
        hass,
        _entry_with_sleep_blocker(),
        [_dark, _occupy, _force_override, _sleep_on, _free, _record_override],
    )
    assert SEEN == [{"override": False}]
    # The blocker switches the lamp off once (step 3); the CLEAR afterwards sends no second OFF.
    assert len(_auto(per_step[3], "turn_off")) == 1
    assert _auto(per_step[4], "turn_off") == []
