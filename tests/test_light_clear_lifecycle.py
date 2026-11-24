"""Lifecycle guard of the automatic CLEAR OFF on the ALL light group.

Real integration and real service events. The automatic OFF is counted on the ALL group entity
with an automation context (no user id). A planned OFF is created with the production scheduler.
Removal is simulated with the same synchronous callback Home Assistant runs on entity removal,
so no sleep is needed.
"""

from __future__ import annotations

import pytest
from homeassistant.components.light import DATA_COMPONENT
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import Context, HomeAssistant

from custom_components.adaptive_areas.const import LightGroupCategory
from custom_components.adaptive_areas.helpers.light_transition import TransitionAction
from custom_components.adaptive_areas.light import AreaLightGroup
from tests import test_light_coordination_regression as regression
from tests.test_light import setup_entities_light_one  # noqa: F401
from tests.test_light_clear_cutover import _auto_off_on_all, _entry, _run
from tests.test_light_coordination_regression import (  # noqa: F401
    CONTROL_SWITCH,
    _dark,
    _free,
    _occupy,
    probe_devices,
)

pytestmark = pytest.mark.usefixtures("probe_devices")


def _group(hass: HomeAssistant) -> AreaLightGroup:
    """Return the current real ALL group entity of the test entry."""
    component = hass.data[DATA_COMPONENT]
    for entity in component.entities:
        if isinstance(entity, AreaLightGroup) and str(entity.category) == str(
            LightGroupCategory.ALL
        ):
            return entity
    raise AssertionError("no runtime ALL group")


def _automation_context() -> Context:
    return Context()


async def test_unload_before_execution_sends_no_off(hass) -> None:
    """A planned OFF whose instance is removed before its task runs sends no service call."""

    async def _plan_and_remove(hass_: HomeAssistant) -> None:
        group = _group(hass_)
        group._async_schedule_command(TransitionAction.TURN_OFF, "area_state_changed")
        group._async_deactivate()  # the removal callback, before the task starts
        await hass_.async_block_till_done()

    per_step = await _run(hass, _entry(), [_dark, _occupy, _free, _plan_and_remove])
    assert len(_auto_off_on_all(per_step[2])) == 1  # the normal CLEAR OFF of step 3
    assert _auto_off_on_all(per_step[3]) == []


async def test_reload_old_instance_sends_no_off(hass) -> None:
    """Reload removes the old instance: its planned OFF is dropped, the new instance works."""
    entry = _entry()

    async def _plan_and_reload(hass_: HomeAssistant) -> None:
        old = _group(hass_)
        old._async_schedule_command(TransitionAction.TURN_OFF, "area_state_changed")
        old._async_deactivate()
        await hass_.config_entries.async_reload(entry.entry_id)
        await hass_.async_block_till_done()
        await regression._enable_group_control(hass_)

    per_step = await _run(
        hass, entry, [_dark, _occupy, _free, _plan_and_reload, _occupy, _free]
    )
    assert _auto_off_on_all(per_step[3]) == []
    assert len(_auto_off_on_all(per_step[5])) == 1


async def test_reoccupied_area_before_execution_sends_no_stale_off(hass) -> None:
    """The planned OFF runs on an occupied Area: it is stale and dropped."""

    async def _reoccupy_then_run(hass_: HomeAssistant) -> None:
        group = _group(hass_)
        planned = group._decision_seq
        # The re-occupation is a new decision input: it supersedes the planned OFF.
        await _occupy(hass_)
        await hass_.async_block_till_done()
        await group._run_group_command(
            TransitionAction.TURN_OFF, planned, "area_state_changed"
        )
        await hass_.async_block_till_done()

    per_step = await _run(hass, _entry(), [_dark, _occupy, _free, _reoccupy_then_run])
    assert _auto_off_on_all(per_step[3]) == []


async def test_disabled_automation_before_execution_sends_no_off(hass) -> None:
    """The automation is switched off after the planning: no OFF is sent."""

    async def _disable_then_run(hass_: HomeAssistant) -> None:
        await hass_.services.async_call(
            "switch",
            "turn_off",
            {ATTR_ENTITY_ID: CONTROL_SWITCH},
            blocking=True,
        )
        await hass_.async_block_till_done()
        group = _group(hass_)
        await group._run_group_command(
            TransitionAction.TURN_OFF, group._decision_seq, "area_state_changed"
        )
        await hass_.async_block_till_done()

    per_step = await _run(hass, _entry(), [_dark, _occupy, _free, _disable_then_run])
    assert _auto_off_on_all(per_step[3]) == []


async def test_new_override_before_execution_sends_no_off(hass) -> None:
    """A manual override set after the planning blocks the OFF."""

    async def _override_then_run(hass_: HomeAssistant) -> None:
        group = _group(hass_)
        group.manual_override = True
        await group._run_group_command(
            TransitionAction.TURN_OFF, group._decision_seq, "area_state_changed"
        )
        await hass_.async_block_till_done()

    per_step = await _run(hass, _entry(), [_dark, _occupy, _free, _override_then_run])
    assert _auto_off_on_all(per_step[3]) == []
