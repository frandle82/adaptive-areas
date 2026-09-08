"""Regression coverage for activity-driven light control."""

import logging
from unittest.mock import Mock

import pytest

from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant

from custom_components.adaptive_areas.const import AreaStates, LightGroupCategory
from custom_components.adaptive_areas.light import AreaLightGroup


@pytest.fixture
def activity_group(hass: HomeAssistant):
    """Build a child group with real HA member states and observable actions."""
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
    for entity_id, state in zip(group._entity_ids, [STATE_ON, STATE_OFF, STATE_OFF]):
        hass.states.async_set(entity_id, state)
    return group


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
    call = Mock()
    monkeypatch.setattr(type(group.hass.services), "call", call)
    expected = activation == "occupied" or (active and activation != "disabled")
    group.area_presence_activity("kitchen", "motion_detected")
    turn_ons = [args for args in call.call_args_list if args.args[1] == "turn_on"]
    assert len(turn_ons) == int(expected)


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
    call = Mock()
    monkeypatch.setattr(type(group.hass.services), "call", call)
    group.area_presence_activity("kitchen", "motion_detected")
    assert sum(args.args[1] == "turn_on" for args in call.call_args_list) == int(
        expected
    )


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
    call = Mock()
    monkeypatch.setattr(type(group.hass.services), "call", call)
    group.area_presence_activity(
        "other" if guard == "other_area" else "kitchen", "motion_detected"
    )
    assert not any(args.args[1] == "turn_on" for args in call.call_args_list)
    if guard == "manual":
        assert group.manual_override
        call.assert_not_called()
    if guard == "released":
        assert not group.controlling


async def test_partial_group_and_dedup(activity_group, monkeypatch):
    """Partial groups activate once per cycle and can retry on later activity."""
    group = activity_group
    clock = Mock(return_value=100)
    monkeypatch.setattr("custom_components.adaptive_areas.light.monotonic", clock)
    call = Mock()
    monkeypatch.setattr(type(group.hass.services), "call", call)
    assert group.area_state_changed(
        "kitchen", ([AreaStates.OCCUPIED], [AreaStates.CLEAR])
    )
    assert not group.area_presence_activity("kitchen", "motion_detected")
    call.assert_called_once()
    clock.return_value = 103
    assert group.area_presence_activity("kitchen", "motion_detected")
    assert call.call_count == 2
    assert group.area.trace_decision.call_args.kwargs["trigger"] == "presence_activity"
    for entity_id in group._entity_ids:
        group.hass.states.async_set(entity_id, STATE_ON)
    clock.return_value = 106
    assert not group.area_presence_activity("kitchen", "motion_detected")
    assert call.call_count == 2
    assert group.area.trace_decision.call_args.kwargs["reason_codes"] == ["already_on"]
