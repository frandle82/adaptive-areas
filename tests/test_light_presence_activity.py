"""Regression coverage for activity-driven light control."""

import logging
from unittest.mock import AsyncMock, Mock

import pytest

from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant

from custom_components.adaptive_areas.const import AreaStates, LightGroupCategory
from custom_components.adaptive_areas.light import AreaLightGroup


@pytest.fixture
def activity_group(hass: HomeAssistant, monkeypatch):
    """Build a child group with real HA member states and observable actions.

    The Area is a Mock without presence sources. Presence availability is therefore set
    to True here: these tests cover the activity logic, not the UNKNOWN presence gate.
    """
    monkeypatch.setattr(
        "custom_components.adaptive_areas.light.area_presence_available",
        lambda area: True,
    )
    group = object.__new__(AreaLightGroup)
    group.hass = hass
    group.area = Mock()
    group.area.id = "kitchen"
    group.area.states = [AreaStates.OCCUPIED, AreaStates.BRIGHT]
    group.area.has_state.side_effect = lambda state: state in group.area.states
    group.area.is_occupied.side_effect = (
        lambda: AreaStates.OCCUPIED in group.area.states
    )
    group.category = LightGroupCategory.OVERHEAD
    group.activation = "occupied"
    group.blocking_states = []
    group.require_dark = False
    group.turn_off_when_bright = False
    group.manual_override = False
    group.controlling = True
    group.controlled = False
    group._last_control_action_ts = float("-inf")
    group._last_turn_on_ts = float("-inf")
    group._entity_ids = ["light.a", "light.b", "light.c"]
    group.entity_id = "light.activity_group"
    group._attr_is_on = True
    group._attr_name = "Activity group"
    group._attr_translation_key = None
    group._attr_extra_state_attributes = {}
    group.logger = logging.getLogger(__name__)
    group.is_control_enabled = Mock(return_value=True)
    # Lifecycle and decision state of a set-up group (commands run on the loop).
    group._active = True
    group.schedule_update_ha_state = Mock()
    group._clear_tasks = set()
    group._decision_previous = None
    group._decision_seq = 0
    group._initial_done = True
    group._pending_action = None
    for entity_id, state in zip(group._entity_ids, [STATE_ON, STATE_OFF, STATE_OFF]):
        hass.states.async_set(entity_id, state)
    hass.states.async_set(group.entity_id, STATE_ON)
    return group


def _record_calls(monkeypatch) -> AsyncMock:
    """Record the automatic group calls (entity, service) made by the shared executor."""
    recorder = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "custom_components.adaptive_areas.light.async_execute_light_entity_action",
        recorder,
    )
    return recorder


def _services(recorder: AsyncMock) -> list[str]:
    return [c.args[2] for c in recorder.await_args_list]


@pytest.mark.parametrize(
    "activation", ["occupied", "extended", "sleep", "accent", "disabled"]
)
@pytest.mark.parametrize("active", [False, True])
async def test_activity_activation(activity_group, activation, active, monkeypatch):
    """Presence only activates a group whose configured state is active."""
    group = activity_group
    group.activation = activation
    if active:
        group.area.states.append(activation)
    recorder = _record_calls(monkeypatch)
    expected = activation == "occupied" or (active and activation != "disabled")
    group.area_presence_activity("kitchen", "motion_detected")
    await group.hass.async_block_till_done()
    assert _services(recorder).count("turn_on") == int(expected)


@pytest.mark.parametrize(
    ("require_dark", "bright_off", "bright", "expected"),
    [
        (False, False, True, True),
        (True, False, True, False),
        (True, False, False, True),
        (False, True, True, False),
        (False, True, False, True),
        (True, True, True, False),
        (True, True, False, True),
    ],
)
async def test_activity_brightness(
    activity_group, monkeypatch, require_dark, bright_off, bright, expected
):
    """All brightness modes retain their current state policy."""
    group = activity_group
    group.require_dark = require_dark
    group.turn_off_when_bright = bright_off
    group.area.states = [
        AreaStates.OCCUPIED,
        AreaStates.BRIGHT if bright else AreaStates.DARK,
    ]
    recorder = _record_calls(monkeypatch)
    group.area_presence_activity("kitchen", "motion_detected")
    await group.hass.async_block_till_done()
    assert _services(recorder).count("turn_on") == int(expected)


@pytest.mark.parametrize(
    "guard", ["blocking", "manual", "released", "disabled", "other_area", "all"]
)
async def test_activity_guards(activity_group, monkeypatch, guard):
    """Activity respects blockers, control switches, overrides and area scope."""
    group = activity_group
    if guard == "blocking":
        group.blocking_states = [AreaStates.BRIGHT]
    elif guard == "manual":
        group.manual_override = True
    elif guard == "released":
        group.controlling = False
    elif guard == "disabled":
        group.is_control_enabled.return_value = False
    elif guard == "all":
        group.category = LightGroupCategory.ALL
    recorder = _record_calls(monkeypatch)
    group.area_presence_activity(
        "other" if guard == "other_area" else "kitchen", "motion_detected"
    )
    await group.hass.async_block_till_done()
    assert "turn_on" not in _services(recorder)
    if guard == "manual":
        assert group.manual_override
        recorder.assert_not_called()
    if guard == "released":
        assert not group.controlling


async def test_partial_group_and_dedup(activity_group, monkeypatch):
    """Activity restores a partly switched group; once all members are on it sends nothing.

    No time window: the duplicate check is the group state (all members on) and the pending
    marker of a command that is still running.
    """
    group = activity_group
    recorder = _record_calls(monkeypatch)
    # A real vacancy first (the decision input of the previous state), then the occupation.
    group.area.states = []
    group.area_state_changed("kitchen", ([AreaStates.CLEAR], [AreaStates.OCCUPIED]))
    group.area.states = [AreaStates.OCCUPIED, AreaStates.BRIGHT]
    group.area_state_changed("kitchen", ([AreaStates.OCCUPIED], [AreaStates.CLEAR]))
    await group.hass.async_block_till_done()
    assert _services(recorder) == ["turn_on"]
    group.area_presence_activity("kitchen", "motion_detected")
    await group.hass.async_block_till_done()
    assert _services(recorder) == ["turn_on", "turn_on"]
    assert group.area.trace_decision.call_args.kwargs["trigger"] == "presence_activity"
    for entity_id in group._entity_ids:
        group.hass.states.async_set(entity_id, STATE_ON)
    group.area_presence_activity("kitchen", "motion_detected")
    await group.hass.async_block_till_done()
    assert _services(recorder) == ["turn_on", "turn_on"]
    assert group.area.trace_decision.call_args.kwargs["reason_codes"] == ["already_on"]
