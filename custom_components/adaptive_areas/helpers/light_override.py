"""Pure manual-override state transitions for the future Light runtime."""

from dataclasses import dataclass
from enum import StrEnum
from collections.abc import Collection

from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN

from custom_components.adaptive_areas.helpers.light_policy import (
    LightPolicyAction,
    LightPolicyDecision,
)


class LightManualOverrideMode(StrEnum):
    """Area-level manual intent that blocks only opposing automation."""

    NONE = "none"
    FORCE_ON = "force_on"
    FORCE_OFF = "force_off"


class LightManualAction(StrEnum):
    """A recognized manual action, independent of HA event detection."""

    TURN_ON = "turn_on"
    TURN_OFF = "turn_off"


class LightOverrideReason(StrEnum):
    """Stable, non-localized result reasons for override filtering."""

    NO_OVERRIDE = "no_override"
    SAME_DIRECTION = "same_direction"
    BLOCKED_BY_FORCE_ON = "blocked_by_force_on"
    BLOCKED_BY_FORCE_OFF = "blocked_by_force_off"


class LightManualDetection(StrEnum):
    """Conservative origin classification for one target state transition."""

    OWN_AUTOMATION = "own_automation"
    MANUAL_ON = "manual_on"
    MANUAL_OFF = "manual_off"
    NOT_MANUAL = "not_manual"


@dataclass(frozen=True, slots=True)
class LightManualOverrideState:
    """Transient area-local manual intent with caller-provided detection time."""

    mode: LightManualOverrideMode = LightManualOverrideMode.NONE
    detected_at: float | None = None


@dataclass(frozen=True, slots=True)
class LightOverrideDecision:
    """Whether a policy decision may proceed under the current override."""

    allowed: bool
    decision: LightPolicyDecision
    reason: LightOverrideReason


def apply_manual_light_action(
    *,
    previous_state: LightManualOverrideState,
    manual_action: LightManualAction,
    now: float,
) -> LightManualOverrideState:
    """Record manual on/off intent as a replacement area-level override."""
    _ = previous_state
    mode = (
        LightManualOverrideMode.FORCE_ON
        if manual_action is LightManualAction.TURN_ON
        else LightManualOverrideMode.FORCE_OFF
    )
    return LightManualOverrideState(mode=mode, detected_at=now)


def apply_manual_override(
    *,
    override_state: LightManualOverrideState,
    decision: LightPolicyDecision,
) -> LightOverrideDecision:
    """Allow policy actions unless they oppose recorded manual intent."""
    if (
        override_state.mode is LightManualOverrideMode.FORCE_ON
        and decision.action is LightPolicyAction.TURN_OFF
    ):
        return LightOverrideDecision(
            False, decision, LightOverrideReason.BLOCKED_BY_FORCE_ON
        )
    if (
        override_state.mode is LightManualOverrideMode.FORCE_OFF
        and decision.action is LightPolicyAction.TURN_ON
    ):
        return LightOverrideDecision(
            False, decision, LightOverrideReason.BLOCKED_BY_FORCE_OFF
        )
    return LightOverrideDecision(
        True,
        decision,
        (
            LightOverrideReason.NO_OVERRIDE
            if override_state.mode is LightManualOverrideMode.NONE
            else LightOverrideReason.SAME_DIRECTION
        ),
    )


def reset_manual_override_for_presence(
    *,
    previous_state: LightManualOverrideState,
    occupied: bool | None,
) -> LightManualOverrideState:
    """Clear manual intent only on confirmed vacancy, never on unavailable presence."""
    if occupied is False:
        return LightManualOverrideState()
    return previous_state


def detect_manual_light_action(
    *, old_state, new_state, own_context_ids: Collection[str]
) -> LightManualDetection:
    """Classify only user-originated real on/off changes for known own contexts."""
    if old_state is None or new_state is None:
        return LightManualDetection.NOT_MANUAL
    old_value, new_value = old_state.state, new_state.state
    if (
        old_value in (STATE_UNAVAILABLE, STATE_UNKNOWN)
        or new_value in (STATE_UNAVAILABLE, STATE_UNKNOWN)
        or (old_value, new_value) not in ((STATE_OFF, STATE_ON), (STATE_ON, STATE_OFF))
    ):
        return LightManualDetection.NOT_MANUAL
    context = new_state.context
    if context.id in own_context_ids or context.parent_id in own_context_ids:
        return LightManualDetection.OWN_AUTOMATION
    if context.user_id is None:
        return LightManualDetection.NOT_MANUAL
    return (
        LightManualDetection.MANUAL_ON
        if new_value == STATE_ON
        else LightManualDetection.MANUAL_OFF
    )
