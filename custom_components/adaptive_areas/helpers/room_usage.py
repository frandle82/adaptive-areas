"""Persistent Cleaning Tracker driven by Adaptive Area presence events."""

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, Self

from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from custom_components.adaptive_areas.const import (
    CLEANING_TRACKER_UPDATE_INTERVAL_SECONDS,
    CONF_FEATURE_ROOM_USAGE,
    CONF_PRESENCE_MINUTES_TO_DUE,
    CONF_PRESENCE_SECONDS_TO_DUE,
    DEFAULT_PRESENCE_MINUTES_TO_DUE,
    DOMAIN,
    AdaptiveAreasEvents,
)

STORAGE_VERSION = 1
STORAGE_KEY_PREFIX = f"{DOMAIN}.cleaning_tracker"


class RoomUsageEngine:
    """Track cumulative presence since an Area was last cleaned."""

    def __init__(self, area) -> None:
        """Initialize an unloaded tracker."""
        self.area = area
        self._store: Store[dict[str, Any]] = Store(
            area.hass,
            STORAGE_VERSION,
            f"{STORAGE_KEY_PREFIX}.{area.id}",
        )
        feature_config = area.feature_config(CONF_FEATURE_ROOM_USAGE)
        if CONF_PRESENCE_MINUTES_TO_DUE in feature_config:
            presence_minutes_to_due = float(
                feature_config[CONF_PRESENCE_MINUTES_TO_DUE]
            )
            self._presence_seconds_to_due = max(1, presence_minutes_to_due * 60)
        else:
            self._presence_seconds_to_due = max(
                1,
                float(
                    feature_config.get(
                        CONF_PRESENCE_SECONDS_TO_DUE,
                        DEFAULT_PRESENCE_MINUTES_TO_DUE * 60,
                    )
                ),
            )
        self._cumulative_presence_seconds = 0.0
        self._last_cleaned: datetime | None = None
        self._occupied = area.is_occupied()
        now = dt_util.utcnow()
        self._last_accounted: datetime | None = now if self._occupied else None
        self._occupied_since: datetime | None = now if self._occupied else None
        self._subscribers: list[Callable[[], None]] = []
        self._remove_listener: Callable[[], None] | None = None
        self._remove_interval: Callable[[], None] | None = None
        self.assessment = self._evaluate(now)

    @classmethod
    async def async_create(cls, area) -> Self:
        """Load persisted state and start tracking an Area."""
        engine = cls(area)
        await engine._async_load()
        engine._remove_listener = async_dispatcher_connect(
            area.hass,
            AdaptiveAreasEvents.AREA_STATE_CHANGED,
            engine._area_state_changed,
        )
        engine._remove_interval = async_track_time_interval(
            area.hass,
            engine._async_periodic_update,
            timedelta(seconds=CLEANING_TRACKER_UPDATE_INTERVAL_SECONDS),
        )
        engine.assessment = engine._evaluate(dt_util.utcnow())
        return engine

    async def _async_load(self) -> None:
        """Load and validate persisted tracker state."""
        stored = await self._store.async_load()
        if not isinstance(stored, dict):
            return
        try:
            cumulative = float(stored.get("cumulative_presence_seconds", 0))
        except TypeError, ValueError:
            cumulative = 0
        self._cumulative_presence_seconds = max(0.0, cumulative)
        last_cleaned = stored.get("last_cleaned")
        if isinstance(last_cleaned, str):
            parsed = dt_util.parse_datetime(last_cleaned)
            if parsed is not None:
                self._last_cleaned = dt_util.as_utc(parsed)

    def _serialize(self) -> dict[str, float | str | None]:
        """Return the persistent representation of current state."""
        return {
            "cumulative_presence_seconds": self._cumulative_presence_seconds,
            "last_cleaned": (
                self._last_cleaned.isoformat() if self._last_cleaned else None
            ),
        }

    async def _async_save(self) -> None:
        """Persist the current tracker state."""
        await self._store.async_save(self._serialize())

    def _accrue(self, now: datetime) -> None:
        """Accrue occupied time exactly once up to now."""
        if not self._occupied or self._last_accounted is None:
            return
        elapsed = (now - self._last_accounted).total_seconds()
        if elapsed > 0:
            self._cumulative_presence_seconds += elapsed
        self._last_accounted = now

    def _evaluate(self, now: datetime) -> dict[str, Any]:
        """Build the public tracker assessment without mutating counters."""
        score = min(
            100.0,
            self._cumulative_presence_seconds / self._presence_seconds_to_due * 100,
        )
        current_duration = (
            max(0, int((now - self._occupied_since).total_seconds()))
            if self._occupied and self._occupied_since
            else 0
        )
        return {
            "score": round(score, 2),
            "due": (self._cumulative_presence_seconds >= self._presence_seconds_to_due),
            "cumulative_presence_seconds": round(self._cumulative_presence_seconds, 3),
            "presence_minutes_to_due": round(self._presence_seconds_to_due / 60, 3),
            "current_occupancy_duration_seconds": current_duration,
            "last_cleaned": (
                self._last_cleaned.isoformat() if self._last_cleaned else None
            ),
        }

    @callback
    def _publish(self, now: datetime) -> None:
        """Refresh the assessment and notify entities."""
        self.assessment = self._evaluate(now)
        for subscriber in list(self._subscribers):
            subscriber()

    @callback
    def _area_state_changed(self, area_id: str, _states_tuple) -> None:
        """Account for transitions reported by the existing Presence engine."""
        if area_id != self.area.id:
            return
        now = dt_util.utcnow()
        self._accrue(now)
        occupied = self.area.is_occupied()
        transitioned = occupied != self._occupied
        if transitioned:
            self._occupied = occupied
            self._last_accounted = now if occupied else None
            self._occupied_since = now if occupied else None
            self.area.trace_decision(
                feature="room_usage",
                trigger="area_state_changed",
                decision="presence_started" if occupied else "presence_stopped",
                outcome="tracked",
                reason_codes=[
                    (
                        "cleaning_presence_started"
                        if occupied
                        else "cleaning_presence_stopped"
                    )
                ],
            )
        self._publish(now)
        self._store.async_delay_save(self._serialize, 1)

    async def _async_periodic_update(self, now: datetime) -> None:
        """Update entities and persistence while the Area remains occupied."""
        if not self._occupied:
            return
        now = dt_util.as_utc(now)
        self._accrue(now)
        self._publish(now)
        await self._async_save()

    async def async_mark_cleaned(self) -> None:
        """Clear accumulated presence and record the cleaning timestamp."""
        now = dt_util.utcnow()
        self._accrue(now)
        self._cumulative_presence_seconds = 0.0
        self._last_cleaned = now
        self._last_accounted = now if self._occupied else None
        self._publish(now)
        await self._async_save()

    async def async_reset(self) -> None:
        """Reset runtime and stored state completely."""
        now = dt_util.utcnow()
        self._cumulative_presence_seconds = 0.0
        self._last_cleaned = None
        self._last_accounted = now if self._occupied else None
        self._publish(now)
        await self._store.async_remove()

    async def async_set_score(self, score: float) -> None:
        """Set score and derive the underlying cumulative presence value."""
        now = dt_util.utcnow()
        self._cumulative_presence_seconds = self._presence_seconds_to_due * score / 100
        self._last_accounted = now if self._occupied else None
        self._publish(now)
        await self._async_save()

    def register_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Register an assessment listener."""
        self._subscribers.append(listener)

        def remove() -> None:
            if listener in self._subscribers:
                self._subscribers.remove(listener)

        return remove

    def _stop(self) -> None:
        """Cancel all listeners and scheduled work idempotently."""
        if self._remove_listener is not None:
            self._remove_listener()
            self._remove_listener = None
        if self._remove_interval is not None:
            self._remove_interval()
            self._remove_interval = None

    async def async_unload(self) -> None:
        """Persist the final occupied interval and release resources."""
        self._stop()
        now = dt_util.utcnow()
        self._accrue(now)
        self._publish(now)
        await self._async_save()
        self._subscribers.clear()

    def unload(self) -> None:
        """Release resources for synchronous callers."""
        self._stop()
        self._subscribers.clear()
