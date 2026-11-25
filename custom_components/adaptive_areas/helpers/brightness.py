"""Brightness classification for an Area: the one source of DARK, BRIGHT and UNKNOWN.

The only input is the configured Lux limits of the light automation and the global
brightness sensor (E2). Classification is pure; the volatile tracker keeps only the
last known DARK or BRIGHT state of one Area and is never persisted (E3, E4).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


# Lux limits of the Light feature: the persisted threshold model (validated, read only).
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


class BrightnessState(StrEnum):
    """Area brightness. UNKNOWN is never treated as dark."""

    DARK = "dark"
    BRIGHT = "bright"
    UNKNOWN = "unknown"


class BrightnessReason(StrEnum):
    """Stable reason code for the resulting state."""

    THRESHOLD_DARK = "threshold_dark"
    THRESHOLD_BRIGHT = "threshold_bright"
    BAND_KEPT = "band_kept"
    BAND_NO_PREVIOUS = "band_no_previous"
    CONFIG_MISSING = "config_missing"
    SOURCE_MISSING = "source_missing"
    SOURCE_UNAVAILABLE = "source_unavailable"


@dataclass(frozen=True, slots=True)
class BrightnessResult:
    """Outcome of one classification; `value` is None when no valid reading exists."""

    state: BrightnessState
    reason: BrightnessReason
    value: float | None = None
    turn_on_below: float | None = None
    turn_off_above: float | None = None


def classify_brightness(
    value: float | None,
    config: LightPolicyConfig | None,
    previous: BrightnessState | None,
    *,
    source_configured: bool = True,
) -> BrightnessResult:
    """Classify one reading against the Lux limits.

    value <= turn_on_below is DARK, value >= turn_off_above is BRIGHT. Inside the band
    the previous DARK or BRIGHT state is kept; without a known previous state the
    result is UNKNOWN. Missing configuration or a missing reading is UNKNOWN.
    """
    if config is None:
        return BrightnessResult(
            BrightnessState.UNKNOWN, BrightnessReason.CONFIG_MISSING
        )
    limits = {
        "turn_on_below": config.turn_on_below,
        "turn_off_above": config.turn_off_above,
    }
    if value is None:
        reason = (
            BrightnessReason.SOURCE_UNAVAILABLE
            if source_configured
            else BrightnessReason.SOURCE_MISSING
        )
        return BrightnessResult(BrightnessState.UNKNOWN, reason, **limits)
    if value <= config.turn_on_below:
        return BrightnessResult(
            BrightnessState.DARK, BrightnessReason.THRESHOLD_DARK, value, **limits
        )
    if value >= config.turn_off_above:
        return BrightnessResult(
            BrightnessState.BRIGHT, BrightnessReason.THRESHOLD_BRIGHT, value, **limits
        )
    if previous in (BrightnessState.DARK, BrightnessState.BRIGHT):
        return BrightnessResult(previous, BrightnessReason.BAND_KEPT, value, **limits)
    return BrightnessResult(
        BrightnessState.UNKNOWN, BrightnessReason.BAND_NO_PREVIOUS, value, **limits
    )


class BrightnessTracker:
    """Volatile per-Area memory of the last known DARK or BRIGHT state.

    The memory is forgotten when the configuration or the source entity changes, and
    when the reading is missing (sensor failure). After recovery, a reading inside the
    band is UNKNOWN until a reading outside the band arrives. Nothing is persisted and
    nothing is derived from light states or service calls.
    """

    def __init__(self) -> None:
        """Start without a remembered state."""
        self._last_known: BrightnessState | None = None
        self._key: tuple | None = None
        self.last_result: BrightnessResult | None = None

    @property
    def last_known(self) -> BrightnessState | None:
        """Return the remembered DARK or BRIGHT state, if any."""
        return self._last_known

    def update(
        self,
        *,
        value: float | None,
        config: LightPolicyConfig | None,
        source_id: str | None,
    ) -> BrightnessResult:
        """Classify one reading and update the memory."""
        key = (
            None
            if config is None or source_id is None
            else (source_id, config.turn_on_below, config.turn_off_above)
        )
        if key != self._key:
            self._last_known = None
            self._key = key
        if value is None:
            self._last_known = None
        result = classify_brightness(
            value, config, self._last_known, source_configured=source_id is not None
        )
        if result.state in (BrightnessState.DARK, BrightnessState.BRIGHT):
            self._last_known = result.state
        self.last_result = result
        return result


def _brightness_limits_config(area) -> dict:
    """Return the Light limits used for the Area brightness (dark and bright).

    The limits are an Area brightness input, so they also apply while the Light feature is
    disabled: the enabled feature configuration, otherwise the parked one (D02). Nothing is
    derived from light states; a missing or incomplete configuration stays UNKNOWN.
    """
    from custom_components.adaptive_areas.const import (  # noqa: PLC0415
        CONF_FEATURE_LIGHT,
        CONF_RETAINED_FEATURES,
    )

    enabled = area.feature_config(CONF_FEATURE_LIGHT)
    if enabled:
        return enabled
    retained = (area.config.get(CONF_RETAINED_FEATURES) or {}).get(CONF_FEATURE_LIGHT)
    return dict(retained) if isinstance(retained, dict) else {}


def area_brightness(hass: HomeAssistant, area) -> BrightnessResult:
    """Evaluate the Area brightness from the global sensor and the light Lux limits."""
    # Local imports keep this module free of Home Assistant state access at import time.
    from custom_components.adaptive_areas.helpers.sources import _numeric_state_value

    tracker = getattr(area, "brightness_tracker", None)
    if tracker is None:
        tracker = BrightnessTracker()
        area.brightness_tracker = tracker
    if area.is_meta():
        return tracker.update(value=None, config=None, source_id=None)
    try:
        config = light_policy_config_from_feature(_brightness_limits_config(area))
    except ValueError:
        config = None
    from custom_components.adaptive_areas.helpers.sources import (  # noqa: PLC0415
        light_illuminance_entity_id,
    )

    source_id = light_illuminance_entity_id(area)
    if source_id is None:
        return tracker.update(value=None, config=config, source_id=None)
    value = _numeric_state_value(hass.states.get(source_id))
    return tracker.update(value=value, config=config, source_id=source_id)
