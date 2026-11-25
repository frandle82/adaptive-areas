"""Lux thresholds of the Light feature: the persisted model and its validation.

Automatic decisions are not made here. Brightness classification and the group decision live in
helpers/brightness.py and helpers/light_transition.py.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite

CONF_TURN_ON_BELOW = "turn_on_below"
CONF_TURN_OFF_ABOVE = "turn_off_above"
CONF_VACANCY_DELAY = "vacancy_delay"


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
