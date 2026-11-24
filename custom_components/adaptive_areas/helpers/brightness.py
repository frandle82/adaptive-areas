"""Brightness classification for an Area: the one source of DARK, BRIGHT and UNKNOWN.

The only input is the configured Lux limits of the light automation and the global
brightness sensor (E2). Classification is pure; the volatile tracker keeps only the
last known DARK or BRIGHT state of one Area and is never persisted (E3, E4).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from custom_components.adaptive_areas.helpers.light_policy import LightPolicyConfig

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


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


def area_brightness(hass: HomeAssistant, area) -> BrightnessResult:
    """Evaluate the Area brightness from the global sensor and the light Lux limits."""
    # Local imports keep this module free of Home Assistant state access at import time.
    from custom_components.adaptive_areas.const import (
        CONF_FEATURE_LIGHT,
        CONF_GLOBAL_LIGHT_SENSOR,
        CONF_GLOBAL_OPTIONS,
    )
    from custom_components.adaptive_areas.helpers.light_policy import (
        light_policy_config_from_feature,
    )
    from custom_components.adaptive_areas.helpers.sources import _numeric_state_value

    tracker = getattr(area, "brightness_tracker", None)
    if tracker is None:
        tracker = BrightnessTracker()
        area.brightness_tracker = tracker
    if area.is_meta() or not area.has_feature(CONF_FEATURE_LIGHT):
        return tracker.update(value=None, config=None, source_id=None)
    try:
        config = light_policy_config_from_feature(
            area.feature_config(CONF_FEATURE_LIGHT)
        )
    except ValueError:
        config = None
    global_options = area.hass_config.options.get(CONF_GLOBAL_OPTIONS, {})
    source_id = (
        global_options.get(CONF_GLOBAL_LIGHT_SENSOR)
        if isinstance(global_options, dict)
        else None
    )
    source_id = source_id if isinstance(source_id, str) and source_id else None
    if source_id is None:
        return tracker.update(value=None, config=config, source_id=None)
    value = _numeric_state_value(hass.states.get(source_id))
    return tracker.update(value=value, config=config, source_id=source_id)
