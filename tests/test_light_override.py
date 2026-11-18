"""Pure manual-override model coverage for the future Light runtime."""

from copy import deepcopy

import pytest
from homeassistant.core import Context, State

from custom_components.adaptive_areas.helpers.light_override import (
    LightManualAction,
    LightManualDetection,
    LightManualOverrideMode,
    LightManualOverrideState,
    LightOverrideReason,
    apply_manual_light_action,
    apply_manual_override,
    detect_manual_light_action,
    reset_manual_override_for_presence,
)
from custom_components.adaptive_areas.helpers.light_policy import (
    LightPolicyAction,
    LightPolicyDecision,
    LightPolicyReason,
)


def _decision(action: LightPolicyAction) -> LightPolicyDecision:
    return LightPolicyDecision(action, LightPolicyReason.WITHIN_HYSTERESIS)


@pytest.mark.parametrize(
    "action", (LightPolicyAction.TURN_ON, LightPolicyAction.TURN_OFF)
)
def test_no_override_allows_automatic_actions(action) -> None:
    """The default state never blocks the policy."""
    result = apply_manual_override(
        override_state=LightManualOverrideState(), decision=_decision(action)
    )
    assert result.allowed
    assert result.reason is LightOverrideReason.NO_OVERRIDE


@pytest.mark.parametrize(
    ("mode", "action", "allowed", "reason"),
    [
        (
            LightManualOverrideMode.FORCE_ON,
            LightPolicyAction.TURN_OFF,
            False,
            LightOverrideReason.BLOCKED_BY_FORCE_ON,
        ),
        (
            LightManualOverrideMode.FORCE_ON,
            LightPolicyAction.TURN_ON,
            True,
            LightOverrideReason.SAME_DIRECTION,
        ),
        (
            LightManualOverrideMode.FORCE_OFF,
            LightPolicyAction.TURN_ON,
            False,
            LightOverrideReason.BLOCKED_BY_FORCE_OFF,
        ),
        (
            LightManualOverrideMode.FORCE_OFF,
            LightPolicyAction.TURN_OFF,
            True,
            LightOverrideReason.SAME_DIRECTION,
        ),
    ],
)
def test_override_filters_only_opposing_automatic_actions(
    mode, action, allowed, reason
) -> None:
    """Manual intent suppresses exactly its opposing automatic direction."""
    decision = _decision(action)
    result = apply_manual_override(
        override_state=LightManualOverrideState(mode, 10), decision=decision
    )
    assert result.allowed is allowed
    assert result.reason is reason
    assert result.decision is decision


@pytest.mark.parametrize(
    ("manual_action", "mode"),
    [
        (LightManualAction.TURN_ON, LightManualOverrideMode.FORCE_ON),
        (LightManualAction.TURN_OFF, LightManualOverrideMode.FORCE_OFF),
    ],
)
def test_manual_action_replaces_area_override(manual_action, mode) -> None:
    """Each recognized manual action defines the current area-wide intent."""
    result = apply_manual_light_action(
        previous_state=LightManualOverrideState(),
        manual_action=manual_action,
        now=12.5,
    )
    assert result == LightManualOverrideState(mode, 12.5)


def test_manual_action_changes_override_direction() -> None:
    """A later manual action replaces, rather than layers onto, prior intent."""
    forced_on = apply_manual_light_action(
        previous_state=LightManualOverrideState(),
        manual_action=LightManualAction.TURN_ON,
        now=1,
    )
    assert apply_manual_light_action(
        previous_state=forced_on,
        manual_action=LightManualAction.TURN_OFF,
        now=2,
    ) == LightManualOverrideState(LightManualOverrideMode.FORCE_OFF, 2)


@pytest.mark.parametrize(
    "mode", (LightManualOverrideMode.FORCE_ON, LightManualOverrideMode.FORCE_OFF)
)
def test_confirmed_vacancy_resets_override(mode) -> None:
    """A completed occupancy cycle clears either direction of manual intent."""
    assert (
        reset_manual_override_for_presence(
            previous_state=LightManualOverrideState(mode, 1), occupied=False
        )
        == LightManualOverrideState()
    )


@pytest.mark.parametrize("occupied", (True, None))
def test_occupied_or_unavailable_presence_preserves_override(occupied) -> None:
    """Only confirmed vacancy may clear manual intent."""
    state = LightManualOverrideState(LightManualOverrideMode.FORCE_ON, 1)
    assert (
        reset_manual_override_for_presence(previous_state=state, occupied=occupied)
        is state
    )


def test_hold_and_no_action_leave_override_and_decisions_unchanged() -> None:
    """Non-actions do not consume or change an override."""
    state = LightManualOverrideState(LightManualOverrideMode.FORCE_OFF, 1)
    for action in (LightPolicyAction.HOLD, LightPolicyAction.NO_ACTION):
        decision = _decision(action)
        result = apply_manual_override(override_state=state, decision=decision)
        assert result.allowed
        assert result.reason is LightOverrideReason.SAME_DIRECTION
        assert result.decision is decision


def test_override_functions_are_deterministic_and_side_effect_free() -> None:
    """Pure model calls neither mutate inputs nor depend on external state."""
    state = LightManualOverrideState(LightManualOverrideMode.FORCE_ON, 5)
    decision = _decision(LightPolicyAction.TURN_OFF)
    state_before, decision_before = deepcopy(state), deepcopy(decision)
    first = apply_manual_override(override_state=state, decision=decision)
    second = apply_manual_override(override_state=state, decision=decision)
    assert first == second
    assert state == state_before
    assert decision == decision_before


def _state(value: str, context: Context) -> State:
    return State("light.room", value, context=context)


@pytest.mark.parametrize(
    ("old_value", "new_value", "context", "own_ids", "expected"),
    [
        ("off", "on", Context(id="own"), {"own"}, LightManualDetection.OWN_AUTOMATION),
        (
            "on",
            "off",
            Context(parent_id="own"),
            {"own"},
            LightManualDetection.OWN_AUTOMATION,
        ),
        ("off", "on", Context(user_id="user"), set(), LightManualDetection.MANUAL_ON),
        ("on", "off", Context(user_id="user"), set(), LightManualDetection.MANUAL_OFF),
        ("off", "on", Context(), set(), LightManualDetection.NOT_MANUAL),
        ("on", "on", Context(user_id="user"), set(), LightManualDetection.NOT_MANUAL),
        (
            "on",
            "unavailable",
            Context(user_id="user"),
            set(),
            LightManualDetection.NOT_MANUAL,
        ),
    ],
)
def test_detect_manual_light_action_is_context_conservative(
    old_value, new_value, context, own_ids, expected
) -> None:
    """Only user-originated real on/off changes become manual intent."""
    assert (
        detect_manual_light_action(
            old_state=_state(old_value, Context()),
            new_state=_state(new_value, context),
            own_context_ids=own_ids,
        )
        is expected
    )


def test_detection_ignores_initial_and_removed_states() -> None:
    """Entity creation and removal cannot invent manual user intent."""
    user_state = _state("on", Context(user_id="user"))
    assert (
        detect_manual_light_action(
            old_state=None, new_state=user_state, own_context_ids=()
        )
        is LightManualDetection.NOT_MANUAL
    )
    assert (
        detect_manual_light_action(
            old_state=user_state, new_state=None, own_context_ids=()
        )
        is LightManualDetection.NOT_MANUAL
    )
