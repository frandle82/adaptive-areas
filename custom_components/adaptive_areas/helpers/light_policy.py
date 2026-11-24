"""Pure decision logic for the future Adaptive Areas Light runtime."""

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from typing import TYPE_CHECKING
from collections.abc import Mapping

if TYPE_CHECKING:
    from custom_components.adaptive_areas.helpers.sources import LightSourceSnapshot

CONF_TURN_ON_BELOW = "turn_on_below"
CONF_TURN_OFF_ABOVE = "turn_off_above"
CONF_VACANCY_DELAY = "vacancy_delay"


class LightPolicyAction(StrEnum):
    """Desired action for a future Light runtime."""

    TURN_ON = "turn_on"
    TURN_OFF = "turn_off"
    HOLD = "hold"
    NO_ACTION = "no_action"


class LightPolicyReason(StrEnum):
    """Stable, non-localized explanation of a policy decision."""

    POLICY_NOT_CONFIGURED = "policy_not_configured"
    NO_TARGETS = "no_targets"
    NO_AVAILABLE_TARGETS = "no_available_targets"
    PRESENCE_UNAVAILABLE = "presence_unavailable"
    UNOCCUPIED = "unoccupied"
    ILLUMINANCE_UNAVAILABLE = "illuminance_unavailable"
    OCCUPIED_AND_DARK = "occupied_and_dark"
    OCCUPIED_AND_BRIGHT = "occupied_and_bright"
    WITHIN_HYSTERESIS = "within_hysteresis"


@dataclass(frozen=True, slots=True)
class LightPolicyConfig:
    """Read-only Lux thresholds; no defaults are implied."""

    turn_on_below: float
    turn_off_above: float

    def __post_init__(self) -> None:
        """Reject invalid or ambiguous hysteresis boundaries."""
        values = (self.turn_on_below, self.turn_off_above)
        if any(
            isinstance(value, bool) or not isinstance(value, (int, float))
            for value in values
        ):
            raise ValueError("Light policy thresholds must be finite numbers")
        if any(not isfinite(value) or value < 0 for value in values):
            raise ValueError("Light policy thresholds must be finite and non-negative")
        # Equal limits are valid (percentage hysteresis of 0 %). Evaluation is then
        # inclusive: at exactly the threshold the light turns on.
        if self.turn_off_above < self.turn_on_below:
            raise ValueError("turn_off_above must not be less than turn_on_below")
        if self.turn_on_below + self.turn_off_above <= 0:
            raise ValueError(
                "the threshold (turn_on_below + turn_off_above) / 2 must be greater than 0"
            )


@dataclass(frozen=True, slots=True)
class LightPolicyDecision:
    """Pure desired action plus its deterministic reason."""

    action: LightPolicyAction
    reason: LightPolicyReason


def light_policy_config_from_feature(
    feature_config: Mapping[str, object],
) -> LightPolicyConfig | None:
    """Build a policy only from a complete persisted Light feature mapping."""
    if not feature_config:
        return None
    keys = {CONF_TURN_ON_BELOW, CONF_TURN_OFF_ABOVE}
    # CONF_VACANCY_DELAY is a retired legacy key: tolerated for old options, never used.
    if not keys <= set(feature_config) or set(feature_config) - (
        keys | {CONF_VACANCY_DELAY}
    ):
        raise ValueError("Light policy requires both thresholds and no other values")
    return LightPolicyConfig(
        turn_on_below=feature_config[CONF_TURN_ON_BELOW],
        turn_off_above=feature_config[CONF_TURN_OFF_ABOVE],
    )


def evaluate_light_policy(
    snapshot: LightSourceSnapshot, policy_config: LightPolicyConfig | None
) -> LightPolicyDecision:
    """Evaluate one source snapshot without runtime, timing, or side effects."""
    if policy_config is None:
        return _decision(
            LightPolicyAction.NO_ACTION, LightPolicyReason.POLICY_NOT_CONFIGURED
        )
    if not snapshot.targets:
        return _decision(LightPolicyAction.NO_ACTION, LightPolicyReason.NO_TARGETS)
    if not any(target.available for target in snapshot.targets):
        return _decision(
            LightPolicyAction.NO_ACTION, LightPolicyReason.NO_AVAILABLE_TARGETS
        )
    if not snapshot.presence_available or snapshot.presence_state is None:
        return _decision(
            LightPolicyAction.NO_ACTION, LightPolicyReason.PRESENCE_UNAVAILABLE
        )
    if not snapshot.presence_state:
        return _decision(LightPolicyAction.TURN_OFF, LightPolicyReason.UNOCCUPIED)
    if not snapshot.illuminance_available or snapshot.illuminance_value is None:
        return _decision(
            LightPolicyAction.NO_ACTION, LightPolicyReason.ILLUMINANCE_UNAVAILABLE
        )
    if snapshot.illuminance_value <= policy_config.turn_on_below:
        return _decision(LightPolicyAction.TURN_ON, LightPolicyReason.OCCUPIED_AND_DARK)
    if snapshot.illuminance_value >= policy_config.turn_off_above:
        return _decision(
            LightPolicyAction.TURN_OFF, LightPolicyReason.OCCUPIED_AND_BRIGHT
        )
    return _decision(LightPolicyAction.HOLD, LightPolicyReason.WITHIN_HYSTERESIS)


def _decision(
    action: LightPolicyAction, reason: LightPolicyReason
) -> LightPolicyDecision:
    """Construct decisions consistently without attaching runtime data."""
    return LightPolicyDecision(action=action, reason=reason)
