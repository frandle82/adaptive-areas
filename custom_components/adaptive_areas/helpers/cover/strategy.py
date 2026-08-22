"""Pure, deterministic Area cover strategy."""

from collections.abc import Mapping
from datetime import time
from typing import Any

from custom_components.adaptive_areas.const import (
    CONF_COVER_CLOSE_BRIGHTNESS,
    CONF_COVER_CLOSE_BRIGHTNESS_ENABLED,
    CONF_COVER_CLOSE_ENABLED,
    CONF_COVER_CLOSE_SLEEP_STARTED,
    CONF_COVER_CLOSE_SUN_ELEVATION,
    CONF_COVER_CLOSE_SUN_ENABLED,
    CONF_COVER_CLOSE_TIME,
    CONF_COVER_CLOSE_TIME_ENABLED,
    CONF_COVER_CLOSE_WINDOW,
    CONF_COVER_FORECAST_ENABLED,
    CONF_COVER_FORECAST_THRESHOLD,
    CONF_COVER_OPEN_BRIGHTNESS,
    CONF_COVER_OPEN_BRIGHTNESS_ENABLED,
    CONF_COVER_OPEN_ENABLED,
    CONF_COVER_OPEN_SLEEP_ENDED,
    CONF_COVER_OPEN_SUN_ELEVATION,
    CONF_COVER_OPEN_SUN_ENABLED,
    CONF_COVER_OPEN_TIME,
    CONF_COVER_OPEN_TIME_ENABLED,
    CONF_COVER_OPEN_WINDOW,
    CONF_COVER_POSITION_CLOSE,
    CONF_COVER_POSITION_OPEN,
    CONF_COVER_POSITION_SHADING,
    CONF_COVER_SHADING_BRIGHTNESS_ENABLED,
    CONF_COVER_SHADING_BRIGHTNESS_THRESHOLD,
    CONF_COVER_SHADING_COVERS,
    CONF_COVER_SHADING_ENABLED,
    CONF_COVER_SHADING_SCOPE,
    CONF_COVER_SHADING_SOURCE,
    CONF_COVER_TEMPERATURE_THRESHOLD,
    COVER_SHADING_SCOPE_SELECTED,
    COVER_SHADING_SOURCE_AREA_CLIMATE,
    DEFAULT_COVER_CLOSE_BRIGHTNESS,
    DEFAULT_COVER_CLOSE_SUN_ELEVATION,
    DEFAULT_COVER_CLOSE_TIME,
    DEFAULT_COVER_FORECAST_THRESHOLD,
    DEFAULT_COVER_OPEN_BRIGHTNESS,
    DEFAULT_COVER_OPEN_SUN_ELEVATION,
    DEFAULT_COVER_OPEN_TIME,
    DEFAULT_COVER_POSITION_CLOSE,
    DEFAULT_COVER_POSITION_OPEN,
    DEFAULT_COVER_POSITION_SHADING,
    DEFAULT_COVER_SHADING_BRIGHTNESS_THRESHOLD,
    DEFAULT_COVER_TEMPERATURE_THRESHOLD,
)

from .models import CoverAction, CoverDecision, CoverInputs


def _time_reached(value: str, now: time, *, opening: bool) -> bool:
    """Compare a configured HH:MM value with local wall time."""
    try:
        hour, minute = (int(part) for part in value.split(":"))
    except AttributeError, TypeError, ValueError:
        return False
    configured = time(hour, minute)
    return now >= configured if opening else now >= configured


def _trigger_request(
    config: Mapping[str, Any], inputs: CoverInputs, *, opening: bool
) -> str | None:
    """Return the stable reason for the first active open/close source."""
    prefix = "open" if opening else "close"
    time_enabled = (
        CONF_COVER_OPEN_TIME_ENABLED if opening else CONF_COVER_CLOSE_TIME_ENABLED
    )
    time_key = CONF_COVER_OPEN_TIME if opening else CONF_COVER_CLOSE_TIME
    time_default = DEFAULT_COVER_OPEN_TIME if opening else DEFAULT_COVER_CLOSE_TIME
    sun_enabled = (
        CONF_COVER_OPEN_SUN_ENABLED if opening else CONF_COVER_CLOSE_SUN_ENABLED
    )
    sun_key = (
        CONF_COVER_OPEN_SUN_ELEVATION if opening else CONF_COVER_CLOSE_SUN_ELEVATION
    )
    sun_default = (
        DEFAULT_COVER_OPEN_SUN_ELEVATION
        if opening
        else DEFAULT_COVER_CLOSE_SUN_ELEVATION
    )
    brightness_enabled = (
        CONF_COVER_OPEN_BRIGHTNESS_ENABLED
        if opening
        else CONF_COVER_CLOSE_BRIGHTNESS_ENABLED
    )
    brightness_key = (
        CONF_COVER_OPEN_BRIGHTNESS if opening else CONF_COVER_CLOSE_BRIGHTNESS
    )
    brightness_default = (
        DEFAULT_COVER_OPEN_BRIGHTNESS if opening else DEFAULT_COVER_CLOSE_BRIGHTNESS
    )
    window_enabled = CONF_COVER_OPEN_WINDOW if opening else CONF_COVER_CLOSE_WINDOW
    sleep_enabled = (
        CONF_COVER_OPEN_SLEEP_ENDED if opening else CONF_COVER_CLOSE_SLEEP_STARTED
    )

    # Edge sources only request an action for the event that caused evaluation.
    if (
        config.get(window_enabled, False)
        and inputs.trigger == f"window_{'open' if opening else 'closed'}"
    ):
        return f"window_{'open' if opening else 'closed'}"
    if (
        config.get(sleep_enabled, False)
        and inputs.trigger == f"sleep_{'ended' if opening else 'started'}"
    ):
        return f"sleep_{'ended' if opening else 'started'}"
    if config.get(time_enabled, False) and (
        inputs.trigger == f"time_{prefix}"
        or _time_reached(
            str(config.get(time_key, time_default)), inputs.now.time(), opening=opening
        )
    ):
        return f"time_{prefix}"
    elevation = inputs.sun_elevation
    if config.get(sun_enabled, False) and elevation is not None:
        threshold = float(config.get(sun_key, sun_default))
        if (opening and elevation >= threshold) or (
            not opening and elevation <= threshold
        ):
            return f"sun_{prefix}"
    brightness = inputs.brightness
    if config.get(brightness_enabled, False) and brightness is not None:
        threshold = float(config.get(brightness_key, brightness_default))
        if (opening and brightness >= threshold) or (
            not opening and brightness <= threshold
        ):
            return f"brightness_{prefix}"
    return None


class CoverStrategy:
    """Evaluate all rules without issuing service calls."""

    def __init__(self, config: Mapping[str, Any], covers: tuple[str, ...]) -> None:
        """Initialize the pure strategy."""
        self.config = config
        self.covers = covers

    def evaluate(self, inputs: CoverInputs) -> CoverDecision:
        """Return one decision using the documented priority order."""
        if self.covers and not inputs.covers_available:
            return CoverDecision(
                reason="blocked_unavailable",
                blocked_by="blocked_unavailable",
                priority=1,
            )
        if inputs.manual_override_until and inputs.manual_override_until > inputs.now:
            return CoverDecision(
                reason="blocked_manual_override",
                blocked_by="blocked_manual_override",
                priority=2,
            )

        close_reason = None
        if self.config.get(CONF_COVER_CLOSE_ENABLED, False):
            close_reason = _trigger_request(self.config, inputs, opening=False)
            if inputs.pending_close and not inputs.windows_open:
                close_reason = close_reason or "window_closed"
        if close_reason:
            if not inputs.close_condition:
                return CoverDecision(
                    reason="blocked_condition",
                    blocked_by="blocked_condition",
                    priority=5,
                )
            target = int(
                self.config.get(CONF_COVER_POSITION_CLOSE, DEFAULT_COVER_POSITION_CLOSE)
            )
            if target == 0 and (inputs.windows_open or not inputs.windows_known):
                return CoverDecision(
                    reason="blocked_window_open",
                    blocked_by="blocked_window_open",
                    priority=3,
                )
            return CoverDecision(
                CoverAction.CLOSE, target, close_reason, priority=5, covers=self.covers
            )

        shade = self._shade_decision(inputs)
        if shade is not None:
            return shade

        if self.config.get(CONF_COVER_OPEN_ENABLED, False):
            open_reason = _trigger_request(self.config, inputs, opening=True)
            if open_reason:
                if inputs.sleep:
                    return CoverDecision(
                        reason="blocked_sleep", blocked_by="blocked_sleep", priority=4
                    )
                if not inputs.open_condition:
                    return CoverDecision(
                        reason="blocked_condition",
                        blocked_by="blocked_condition",
                        priority=7,
                    )
                return CoverDecision(
                    CoverAction.OPEN,
                    int(
                        self.config.get(
                            CONF_COVER_POSITION_OPEN, DEFAULT_COVER_POSITION_OPEN
                        )
                    ),
                    open_reason,
                    priority=7,
                    covers=self.covers,
                )
        return CoverDecision()

    def _shade_decision(self, inputs: CoverInputs) -> CoverDecision | None:
        if not self.config.get(CONF_COVER_SHADING_ENABLED, False):
            return None
        if not inputs.shading_condition:
            return CoverDecision(
                reason="blocked_condition", blocked_by="blocked_condition", priority=6
            )

        source = self.config.get(
            CONF_COVER_SHADING_SOURCE, COVER_SHADING_SOURCE_AREA_CLIMATE
        )
        thermal_reason = None
        if source == COVER_SHADING_SOURCE_AREA_CLIMATE:
            if inputs.area_climate_enabled:
                if inputs.area_climate_heat == "required":
                    thermal_reason = "indoor_heat_required"
                elif inputs.area_climate_heat == "recommended":
                    thermal_reason = "indoor_heat"
        elif (
            inputs.fallback_temperature is not None
            and inputs.fallback_temperature
            >= float(
                self.config.get(
                    CONF_COVER_TEMPERATURE_THRESHOLD,
                    DEFAULT_COVER_TEMPERATURE_THRESHOLD,
                )
            )
        ):
            thermal_reason = "indoor_heat"

        forecast_reason = None
        if (
            self.config.get(CONF_COVER_FORECAST_ENABLED, False)
            and inputs.forecast_temperature is not None
        ):
            if inputs.forecast_temperature >= float(
                self.config.get(
                    CONF_COVER_FORECAST_THRESHOLD, DEFAULT_COVER_FORECAST_THRESHOLD
                )
            ):
                forecast_reason = "forecast_heat"
        reason = thermal_reason or forecast_reason
        if reason is None:
            return None
        reason_codes = [reason]
        if self.config.get(CONF_COVER_SHADING_BRIGHTNESS_ENABLED, False):
            shading_brightness = (
                inputs.shading_brightness
                if inputs.shading_brightness is not None
                else inputs.brightness
            )
            if shading_brightness is None or shading_brightness < float(
                self.config.get(
                    CONF_COVER_SHADING_BRIGHTNESS_THRESHOLD,
                    DEFAULT_COVER_SHADING_BRIGHTNESS_THRESHOLD,
                )
            ):
                return None
            reason_codes.append("brightness_confirmed_heat")
        covers = self.covers
        if self.config.get(CONF_COVER_SHADING_SCOPE) == COVER_SHADING_SCOPE_SELECTED:
            selected = set(self.config.get(CONF_COVER_SHADING_COVERS, []))
            covers = tuple(entity_id for entity_id in covers if entity_id in selected)
        return CoverDecision(
            CoverAction.SHADE,
            int(
                self.config.get(
                    CONF_COVER_POSITION_SHADING, DEFAULT_COVER_POSITION_SHADING
                )
            ),
            reason,
            priority=6,
            covers=covers,
            reason_codes=tuple(reason_codes),
        )
