"""Event-driven orchestration for Area cover control."""

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.cover.const import DOMAIN as COVER_DOMAIN
from homeassistant.components.weather import SERVICE_GET_FORECASTS
from homeassistant.components.weather.const import DOMAIN as WEATHER_DOMAIN
from homeassistant.const import ATTR_DEVICE_CLASS, ATTR_ENTITY_ID, STATE_ON
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.util import dt as dt_util

from custom_components.adaptive_areas.base.adaptive import AdaptiveArea
from custom_components.adaptive_areas.const import (
    AREA_STATE_SLEEP,
    CONF_COVER_BRIGHTNESS_ENTITY,
    CONF_COVER_CLOSE_TIME,
    CONF_COVER_CLOSE_TIME_ENABLED,
    CONF_COVER_FORECAST_ENTITY,
    CONF_COVER_FORECAST_ENABLED,
    CONF_COVER_MANUAL_OVERRIDE_ENABLED,
    CONF_COVER_MANUAL_OVERRIDE_MINUTES,
    CONF_COVER_OPEN_TIME,
    CONF_COVER_OPEN_TIME_ENABLED,
    CONF_COVER_OPEN_CONDITION,
    CONF_COVER_CLOSE_CONDITION,
    CONF_COVER_SHADING_CONDITION,
    CONF_COVER_SHADING_BRIGHTNESS_THRESHOLD,
    CONF_COVER_TEMPERATURE_THRESHOLD,
    CONF_COVER_TEMPERATURE_ENTITY,
    CONF_ENVIRONMENT_WINDOWS,
    CONF_FEATURE_ENVIRONMENT,
    AdaptiveAreasEvents,
    DEFAULT_COVER_MANUAL_OVERRIDE_MINUTES,
    DEFAULT_COVER_SHADING_BRIGHTNESS_THRESHOLD,
    DEFAULT_COVER_TEMPERATURE_THRESHOLD,
)

from .actuator import CoverActuator
from .models import CoverDecision, CoverInputs, CoverRuntimeState
from .strategy import CoverStrategy

_LOGGER = logging.getLogger(__name__)
# Covers often report opening/closing and final position over tens of seconds.
OWN_COMMAND_WINDOW = timedelta(seconds=120)
FALLBACK_TEMPERATURE_HYSTERESIS = 0.5
BRIGHTNESS_HYSTERESIS_RATIO = 0.05


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except TypeError, ValueError:
        return None
    return result if result == result else None


class AreaCoverController:
    """Collect measurements, evaluate strategy, then invoke the actuator."""

    def __init__(self, area: AdaptiveArea) -> None:
        """Initialize one Area controller."""
        self.area = area
        self.hass: HomeAssistant = area.hass
        self.config = area.feature_config("cover_groups")
        self.covers = tuple(
            entity[ATTR_ENTITY_ID] for entity in area.entities.get(COVER_DOMAIN, [])
        )
        self.strategy = CoverStrategy(self.config, self.covers)
        self.runtime = CoverRuntimeState()
        self.actuator = CoverActuator(self.hass, self._mark_own_command)
        self._remove_callbacks: list[Callable[[], None]] = []
        self._override_timer: Callable[[], None] | None = None
        self._evaluation_lock = asyncio.Lock()
        self._previous_windows_open: bool | None = None
        self._previous_sleep = area.has_state(AREA_STATE_SLEEP)
        self._subscribers: list[Callable[[], None]] = []

    @property
    def window_ids(self) -> tuple[str, ...]:
        """Return explicit Area Climate windows or discovered Area windows."""
        configured = self.area.config.get(CONF_ENVIRONMENT_WINDOWS, [])
        if configured:
            return tuple(configured)
        return tuple(
            entity[ATTR_ENTITY_ID]
            for entity in self.area.entities.get("binary_sensor", [])
            if (state := self.hass.states.get(entity[ATTR_ENTITY_ID])) is not None
            and state.attributes.get(ATTR_DEVICE_CLASS)
            in (BinarySensorDeviceClass.WINDOW, BinarySensorDeviceClass.OPENING)
        )

    async def async_start(self) -> None:
        """Subscribe to relevant state and time events."""
        tracked = set(self.covers) | set(self.window_ids)
        tracked.update(
            entity_id
            for key in (
                CONF_COVER_BRIGHTNESS_ENTITY,
                CONF_COVER_TEMPERATURE_ENTITY,
                CONF_COVER_FORECAST_ENTITY,
                CONF_COVER_OPEN_CONDITION,
                CONF_COVER_CLOSE_CONDITION,
                CONF_COVER_SHADING_CONDITION,
            )
            if (entity_id := self.config.get(key))
        )
        tracked.add("sun.sun")
        self._remove_callbacks.append(
            async_track_state_change_event(self.hass, tracked, self._state_changed)
        )
        if self.area.environment is not None:
            self._remove_callbacks.append(
                self.area.environment.register_listener(self._environment_changed)
            )
        self._remove_callbacks.append(
            async_dispatcher_connect(
                self.hass,
                AdaptiveAreasEvents.AREA_STATE_CHANGED,
                self._area_state_changed,
            )
        )
        self._schedule_time(
            CONF_COVER_OPEN_TIME_ENABLED, CONF_COVER_OPEN_TIME, "time_open"
        )
        self._schedule_time(
            CONF_COVER_CLOSE_TIME_ENABLED, CONF_COVER_CLOSE_TIME, "time_close"
        )
        await self.async_evaluate("config_reload")

    def async_stop(self) -> None:
        """Remove all owned listeners and timers."""
        for remove in self._remove_callbacks:
            remove()
        self._remove_callbacks.clear()
        if self._override_timer is not None:
            self._override_timer()
            self._override_timer = None

    def _schedule_time(self, enabled_key: str, value_key: str, trigger: str) -> None:
        if not self.config.get(enabled_key, False):
            return
        try:
            hour, minute = (int(part) for part in self.config[value_key].split(":"))
        except KeyError, TypeError, ValueError:
            return

        @callback
        def reached(_now: datetime) -> None:
            self.hass.async_create_task(self.async_evaluate(trigger))

        self._remove_callbacks.append(
            async_track_time_change(
                self.hass, reached, hour=hour, minute=minute, second=0
            )
        )

    @callback
    def _environment_changed(self) -> None:
        self.hass.async_create_task(self.async_evaluate("area_climate"))

    @callback
    def _state_changed(self, event: Event) -> None:
        entity_id = event.data["entity_id"]
        if entity_id in self.covers:
            old_state = event.data.get("old_state")
            new_state = event.data.get("new_state")
            old_position = (
                old_state.attributes.get("current_position") if old_state else None
            )
            new_position = (
                new_state.attributes.get("current_position") if new_state else None
            )
            was_available = old_state is not None and old_state.state not in (
                "unknown",
                "unavailable",
            )
            movement = bool(
                was_available
                and new_state is not None
                and (
                    new_state.state in ("opening", "closing")
                    or old_position != new_position
                    or old_state.state != new_state.state
                )
            )
            if movement:
                self._detect_manual_movement(entity_id)
            trigger = "cover_state"
        elif entity_id in self.window_ids:
            open_now, _known = self._window_state()
            trigger = "window_open" if open_now else "window_closed"
        elif entity_id == "sun.sun":
            trigger = "sun"
        else:
            trigger = "input_changed"
        self.hass.async_create_task(self.async_evaluate(trigger))

    @callback
    def _area_state_changed(self, area_id: str, _states: Any) -> None:
        """Evaluate after the Area sleep state changes."""
        if area_id != self.area.id:
            return
        sleep = self.area.has_state(AREA_STATE_SLEEP)
        trigger = "sleep_started" if sleep else "sleep_ended"
        self._previous_sleep = sleep
        self.hass.async_create_task(self.async_evaluate(trigger))

    def _mark_own_command(self, entity_id: str, now: datetime) -> None:
        self.runtime.own_commands[entity_id] = now

    def _detect_manual_movement(self, entity_id: str) -> None:
        if not self.config.get(CONF_COVER_MANUAL_OVERRIDE_ENABLED, True):
            return
        now = dt_util.utcnow()
        own = self.runtime.own_commands.get(entity_id)
        if own is not None and now - own <= OWN_COMMAND_WINDOW:
            return
        minutes = int(
            self.config.get(
                CONF_COVER_MANUAL_OVERRIDE_MINUTES,
                DEFAULT_COVER_MANUAL_OVERRIDE_MINUTES,
            )
        )
        self.runtime.manual_override_until = now + timedelta(minutes=minutes)
        if self._override_timer is not None:
            self._override_timer()

        @callback
        def expired(_now: datetime) -> None:
            self._override_timer = None
            self.runtime.manual_override_until = None
            self.hass.async_create_task(self.async_evaluate("override_expired"))

        self._override_timer = async_call_later(self.hass, minutes * 60, expired)

    def _window_state(self) -> tuple[bool, bool]:
        states = [self.hass.states.get(entity_id) for entity_id in self.window_ids]
        if not states:
            return False, True
        known = all(
            state is not None and state.state not in ("unknown", "unavailable")
            for state in states
        )
        return (
            any(state is not None and state.state == STATE_ON for state in states),
            known,
        )

    def _condition(self, key: str) -> bool:
        entity_id = self.config.get(key)
        if not entity_id:
            return True
        state = self.hass.states.get(entity_id)
        return state is not None and state.state == STATE_ON

    def _forecast_temperature(self) -> float | None:
        entity_id = self.config.get(CONF_COVER_FORECAST_ENTITY)
        state = self.hass.states.get(entity_id) if entity_id else None
        if self.runtime.forecast_temperature is not None:
            return self.runtime.forecast_temperature
        if state is None:
            return None
        values = [
            _number(item.get("temperature"))
            for item in state.attributes.get("forecast", [])
            if isinstance(item, dict)
        ]
        valid = [value for value in values if value is not None]
        return max(valid) if valid else _number(state.attributes.get("temperature"))

    async def _async_update_forecast(self) -> None:
        """Refresh the simple daily maximum from Home Assistant weather data."""
        self.runtime.forecast_temperature = None
        entity_id = self.config.get(CONF_COVER_FORECAST_ENTITY)
        if not self.config.get(CONF_COVER_FORECAST_ENABLED, False) or not entity_id:
            return
        if not self.hass.services.has_service(WEATHER_DOMAIN, SERVICE_GET_FORECASTS):
            return
        try:
            response = await self.hass.services.async_call(
                WEATHER_DOMAIN,
                SERVICE_GET_FORECASTS,
                {ATTR_ENTITY_ID: entity_id, "type": "daily"},
                blocking=True,
                return_response=True,
            )
        except Exception:  # noqa: BLE001 - missing provider data is non-fatal
            _LOGGER.debug("Forecast unavailable for %s", entity_id, exc_info=True)
            return
        payload = response.get(entity_id, {}) if isinstance(response, dict) else {}
        forecast = payload.get("forecast", []) if isinstance(payload, dict) else []
        values = [
            _number(item.get("temperature"))
            for item in forecast
            if isinstance(item, dict)
        ]
        valid = [value for value in values if value is not None]
        if valid:
            self.runtime.forecast_temperature = max(valid)

    def _inputs(self, trigger: str) -> CoverInputs:
        windows_open, windows_known = self._window_state()
        brightness_entity = self.config.get(CONF_COVER_BRIGHTNESS_ENTITY)
        temperature_entity = self.config.get(CONF_COVER_TEMPERATURE_ENTITY)
        brightness_state = (
            self.hass.states.get(brightness_entity) if brightness_entity else None
        )
        temperature_state = (
            self.hass.states.get(temperature_entity) if temperature_entity else None
        )
        sun = self.hass.states.get("sun.sun")
        brightness = _number(brightness_state.state) if brightness_state else None
        fallback_temperature = (
            _number(temperature_state.state) if temperature_state else None
        )
        temperature_threshold = float(
            self.config.get(
                CONF_COVER_TEMPERATURE_THRESHOLD,
                DEFAULT_COVER_TEMPERATURE_THRESHOLD,
            )
        )
        if fallback_temperature is not None:
            if self.runtime.fallback_heat_active:
                self.runtime.fallback_heat_active = (
                    fallback_temperature
                    >= temperature_threshold - FALLBACK_TEMPERATURE_HYSTERESIS
                )
            else:
                self.runtime.fallback_heat_active = (
                    fallback_temperature >= temperature_threshold
                )
            if self.runtime.fallback_heat_active:
                fallback_temperature = max(fallback_temperature, temperature_threshold)
        brightness_threshold = float(
            self.config.get(
                CONF_COVER_SHADING_BRIGHTNESS_THRESHOLD,
                DEFAULT_COVER_SHADING_BRIGHTNESS_THRESHOLD,
            )
        )
        if brightness is not None:
            if self.runtime.brightness_gate_active:
                self.runtime.brightness_gate_active = (
                    brightness
                    >= brightness_threshold * (1 - BRIGHTNESS_HYSTERESIS_RATIO)
                )
            else:
                self.runtime.brightness_gate_active = brightness >= brightness_threshold
        shading_brightness = brightness
        if self.runtime.brightness_gate_active and brightness is not None:
            shading_brightness = max(brightness, brightness_threshold)
        demand = "unknown"
        if self.area.environment is not None:
            demand = str(
                self.area.environment.assessment.get(
                    "heat_protection_demand", "unknown"
                )
            )
        return CoverInputs(
            now=dt_util.now(),
            trigger=trigger,
            sleep=self.area.has_state(AREA_STATE_SLEEP),
            windows_open=windows_open,
            windows_known=windows_known,
            brightness=brightness,
            shading_brightness=shading_brightness,
            sun_elevation=_number(sun.attributes.get("elevation")) if sun else None,
            area_climate_enabled=self.area.has_feature(CONF_FEATURE_ENVIRONMENT),
            area_climate_heat=demand,
            fallback_temperature=fallback_temperature,
            forecast_temperature=self._forecast_temperature(),
            open_condition=self._condition(CONF_COVER_OPEN_CONDITION),
            close_condition=self._condition(CONF_COVER_CLOSE_CONDITION),
            shading_condition=self._condition(CONF_COVER_SHADING_CONDITION),
            manual_override_until=self.runtime.manual_override_until,
            pending_close=self.runtime.pending_close,
            covers_available=any(
                (state := self.hass.states.get(entity_id)) is not None
                and state.state not in ("unknown", "unavailable")
                for entity_id in self.covers
            ),
        )

    async def async_evaluate(self, trigger: str) -> CoverDecision:
        """Run a full evaluation and apply only the resulting decision."""
        async with self._evaluation_lock:
            await self._async_update_forecast()
            inputs = self._inputs(trigger)
            decision = self.strategy.evaluate(inputs)
            if decision.reason == "blocked_window_open":
                self.runtime.pending_close = True
            elif decision.action.value == "close":
                self.runtime.pending_close = False
            unsupported, unavailable = await self.actuator.async_apply(decision)
            self.runtime.unsupported_covers = unsupported
            self.runtime.unavailable_covers = unavailable
            not_actionable = set(unsupported) | set(unavailable)
            if unsupported and not set(decision.covers) - not_actionable:
                decision = CoverDecision(
                    reason="unsupported_position",
                    blocked_by="unsupported_position",
                    priority=decision.priority,
                    covers=decision.covers,
                )
            elif unavailable and not set(decision.covers) - not_actionable:
                decision = CoverDecision(
                    reason="blocked_unavailable",
                    blocked_by="blocked_unavailable",
                    priority=1,
                    covers=decision.covers,
                )
            self.runtime.last_decision = decision
            self.area.trace_decision(
                feature="cover_control",
                trigger=trigger,
                decision=decision.action.value,
                outcome="blocked" if decision.blocked_by else "evaluated",
                reason_codes=(
                    list(decision.reason_codes)
                    if decision.reason_codes
                    else [decision.reason] if decision.reason else []
                ),
            )
            for subscriber in list(self._subscribers):
                subscriber()
            return decision

    def register_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Register a diagnostics listener."""
        self._subscribers.append(listener)

        def remove() -> None:
            if listener in self._subscribers:
                self._subscribers.remove(listener)

        return remove

    @property
    def diagnostics(self) -> dict[str, Any]:
        """Return dashboard-neutral diagnostics for group attributes."""
        decision = self.runtime.last_decision
        selected = self.covers
        if self.config.get("shading_scope") == "selected":
            configured = set(self.config.get("shading_covers", []))
            selected = tuple(
                entity_id for entity_id in self.covers if entity_id in configured
            )
        return {
            "cover_control": {
                "action": decision.action.value,
                "target_position": decision.target_position,
                "reason": decision.reason,
                "reason_codes": list(decision.reason_codes),
                "blocked_by": decision.blocked_by,
                "manual_override": self.runtime.manual_override_until is not None,
                "manual_override_until": self.runtime.manual_override_until,
                "pending_close": self.runtime.pending_close,
                "unsupported_covers": list(self.runtime.unsupported_covers),
                "unavailable_covers": list(self.runtime.unavailable_covers),
            },
            "shading": {
                "enabled": bool(self.config.get("shading_enabled", False)),
                "source": self.config.get("shading_temperature_source", "area_climate"),
                "forecast_triggered": decision.reason == "forecast_heat",
                "brightness_gate": bool(
                    self.config.get("shading_brightness_enabled", False)
                ),
                "selected_covers": list(selected),
            },
        }
