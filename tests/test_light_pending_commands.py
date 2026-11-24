"""Pending automatic commands on the shared path: duplicates and superseded commands.

Real HA service calls on the overhead group entity (automation context). No sleeps.
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant

from custom_components.adaptive_areas.const import LightGroupCategory
from custom_components.adaptive_areas.helpers.light_transition import TransitionAction
from tests.test_light_clear_cutover import _entry, _run
from tests.test_light_coordination_regression import (  # noqa: F401
    _dark,
    _occupy,
    probe_devices,
)
from tests.test_light import setup_entities_light_one  # noqa: F401

pytestmark = pytest.mark.usefixtures("probe_devices")

OVERHEAD = "light.adaptive_areas_light_groups_kitchen_overhead_lights"


def _overhead(hass: HomeAssistant):
    from homeassistant.components.light import DATA_COMPONENT

    from custom_components.adaptive_areas.light import AreaLightGroup

    for entity in hass.data[DATA_COMPONENT].entities:
        if isinstance(entity, AreaLightGroup) and str(entity.category) == str(
            LightGroupCategory.OVERHEAD
        ):
            return entity
    raise AssertionError("no overhead group")


def _auto(events: list[dict], service: str) -> list[dict]:
    return [
        e
        for e in events
        if e["service"] == service and e["target"] == OVERHEAD and not e["user"]
    ]


async def test_identical_pending_commands_are_sent_once(hass) -> None:
    """Two identical decisions while the first is still pending: one ON call."""

    async def _two_identical(hass_: HomeAssistant) -> None:
        group = _overhead(hass_)
        group._async_schedule_command(TransitionAction.TURN_ON, "area_state_changed")
        group._async_schedule_command(TransitionAction.TURN_ON, "area_state_changed")
        await hass_.async_block_till_done()

    per = await _run(hass, _entry(), [_dark, _two_identical])
    assert len(_auto(per[1], "turn_on")) == 1


async def test_superseded_pending_command_is_dropped(hass) -> None:
    """A planned OFF superseded by a newer ON (lamps on): no contradictory automatic call."""

    async def _off_then_on(hass_: HomeAssistant) -> None:
        group = _overhead(hass_)
        group._async_schedule_command(TransitionAction.TURN_OFF, "area_state_changed")
        group._async_schedule_command(TransitionAction.TURN_ON, "area_state_changed")
        await hass_.async_block_till_done()

    per = await _run(hass, _entry(), [_dark, _occupy, _off_then_on])
    assert len(_auto(per[1], "turn_on")) == 1
    assert _auto(per[2], "turn_off") == []
    assert _auto(per[2], "turn_on") == []


async def test_two_events_while_pending_give_one_decision(hass) -> None:
    """Occupation and a repeated occupation signal in one tick: one ON, no second call."""

    async def _occupy_twice(hass_: HomeAssistant) -> None:
        await _occupy(hass_)
        await _occupy(hass_)
        await hass_.async_block_till_done()

    per = await _run(hass, _entry(), [_dark, _occupy_twice])
    assert len(_auto(per[1], "turn_on")) == 1
