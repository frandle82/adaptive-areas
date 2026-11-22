"""Event sequence: manual switch-off, continued darkness, vacancy and presence unknown."""

from custom_components.adaptive_areas.helpers.light_override import (
    LightManualAction,
    LightManualOverrideMode,
    LightManualOverrideState,
    apply_manual_light_action,
    apply_manual_override,
    reset_manual_override_for_presence,
)
from custom_components.adaptive_areas.helpers.light_policy import (
    LightPolicyAction,
    LightPolicyDecision,
    LightPolicyReason,
)


def _turn_on() -> LightPolicyDecision:
    return LightPolicyDecision(
        LightPolicyAction.TURN_ON, LightPolicyReason.OCCUPIED_AND_DARK
    )


def test_manual_off_blocks_auto_on_until_confirmed_vacancy() -> None:
    """Sequence: auto on -> manual off -> still dark and occupied -> vacancy releases it."""
    state = LightManualOverrideState()

    # 1. Policy wants to turn on, no manual intent yet.
    assert apply_manual_override(override_state=state, decision=_turn_on()).allowed

    # 2. The user switches the light off by hand while the room is occupied.
    state = apply_manual_light_action(
        previous_state=state, manual_action=LightManualAction.TURN_OFF, now=10.0
    )
    assert state.mode is LightManualOverrideMode.FORCE_OFF

    # 3. Still dark and occupied, a new sensor value evaluates again: blocked.
    state = reset_manual_override_for_presence(previous_state=state, occupied=True)
    assert not apply_manual_override(override_state=state, decision=_turn_on()).allowed

    # 4. Presence unknown does not clear manual intent (conservative).
    state = reset_manual_override_for_presence(previous_state=state, occupied=None)
    assert state.mode is LightManualOverrideMode.FORCE_OFF
    assert not apply_manual_override(override_state=state, decision=_turn_on()).allowed

    # 5. Confirmed vacancy clears the intent; the next occupied evaluation may turn on.
    state = reset_manual_override_for_presence(previous_state=state, occupied=False)
    assert state.mode is LightManualOverrideMode.NONE
    assert apply_manual_override(override_state=state, decision=_turn_on()).allowed


def test_manual_on_blocks_only_auto_off() -> None:
    """Manual on keeps the light on against TURN_OFF but never blocks TURN_ON."""
    state = apply_manual_light_action(
        previous_state=LightManualOverrideState(),
        manual_action=LightManualAction.TURN_ON,
        now=1.0,
    )
    assert apply_manual_override(override_state=state, decision=_turn_on()).allowed
    off = LightPolicyDecision(
        LightPolicyAction.TURN_OFF, LightPolicyReason.OCCUPIED_AND_BRIGHT
    )
    assert not apply_manual_override(override_state=state, decision=off).allowed
